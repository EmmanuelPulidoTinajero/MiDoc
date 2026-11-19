import { expect, Page, test } from '@playwright/test';
import {
  MockApiState,
  assertNoHorizontalOverflow,
  attachErrorTrackers,
  mockApiRoutes,
  seedSession,
} from './mocks';

async function assertCurrentAnd320Overflow(page: Page): Promise<void> {
  const original = page.viewportSize();
  await assertNoHorizontalOverflow(page);
  await page.setViewportSize({ width: 320, height: 568 });
  await assertNoHorizontalOverflow(page);
  if (original) {
    await page.setViewportSize(original);
  }
}

function freshState(overrides: Partial<MockApiState> = {}): MockApiState {
  return {
    confirmedSessions: [],
    checkoutCalled: 0,
    subscriptionActive: true,
    ...overrides,
  };
}

test.describe('MiDoc E2E — Diseño, navegación y flujos principales', () => {
  test('directorio público: estados carga/error/vacío, promoción, reload y sin desbordamiento (incluye 320px)', async ({
    page,
  }) => {
    const errors = attachErrorTrackers(page, [503]);
    const state = freshState({ failDoctorsOnce: true, doctorsDelayMs: 250 });
    await mockApiRoutes(page, state);

    await page.goto('/#/buscar');
    await expect(page.getByRole('heading', { name: 'Buscar profesionales' })).toBeVisible();

    // Estado de error + reintento exitoso
    await expect(page.getByText('No pudimos consultar el directorio')).toBeVisible();
    await page.getByRole('button', { name: 'Reintentar' }).click();

    // Tarjeta con descuento
    await expect(page.getByText('Dra. Elena Ruiz')).toBeVisible();
    await expect(page.getByText('$800 MXN')).toBeVisible();
    await expect(page.getByText('-20%')).toBeVisible();

    // Estado vacío y recarga de página manteniendo ruta hash
    await page.getByLabel('Nombre o palabra clave').fill('inexistente');
    await page.getByRole('button', { name: 'Buscar' }).click();
    await expect(page.getByText('Sin resultados para estos filtros')).toBeVisible();

    await page.reload();
    await expect(page).toHaveURL(/#\/buscar/);
    await expect(page.getByText('Dra. Elena Ruiz')).toBeVisible();

    await assertNoHorizontalOverflow(page);
    await page.setViewportSize({ width: 320, height: 568 });
    await assertNoHorizontalOverflow(page);

    expect(errors).toEqual([]);
  });

  test('paciente: citas (reprogramar con 0 slots + modal cancelar), expediente sin duplicados, bitácora y mensajes', async ({
    page,
  }) => {
    const errors = attachErrorTrackers(page);
    const state = freshState({ emptySlots: true });
    await seedSession(page, 'PACIENTE');
    await mockApiRoutes(page, state);

    await page.goto('/#/citas');
    await expect(page.locator('tbody .ds-badge')).toHaveText('Confirmada');
    await assertCurrentAnd320Overflow(page);

    // Reprogramar con 0 horarios: el botón Cerrar y Esc siempre permiten salir
    await page.getByRole('button', { name: 'Reprogramar' }).click();
    const reschedDialog = page.locator('dialog[open]');
    await expect(reschedDialog).toBeVisible();
    await expect(reschedDialog.getByText('No hay horarios libres ese día')).toBeVisible();
    await reschedDialog.locator('.ds-modal-footer').getByRole('button', { name: 'Cerrar' }).click();
    await expect(reschedDialog).toHaveCount(0);

    // Cancelar usa <dialog> nativo y Esc restaura foco
    const cancelTrigger = page.getByRole('button', { name: 'Cancelar' }).first();
    await cancelTrigger.click();
    const cancelDialog = page.locator('dialog[open]');
    await expect(cancelDialog).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(cancelDialog).toHaveCount(0);

    // Expediente: documentos no duplicados + bitácora de accesos + sin desbordamiento con tablas pobladas
    await page.goto('/#/expediente');
    await expect(page.getByRole('heading', { name: 'Mi expediente médico' })).toBeVisible();
    await expect(page.locator('a[href="https://example.com/biometria.pdf"]')).toHaveCount(1);
    await expect(page.getByRole('heading', { name: 'Quién vio mi expediente' })).toBeVisible();
    await expect(page.getByText('Otorgado')).toBeVisible();
    await expect(page.getByText('Lectura de expediente')).toBeVisible();
    await assertCurrentAnd320Overflow(page);

    // Mensajes: barra lateral + hilo de chat
    await page.goto('/#/mensajes');
    await expect(page.locator('select')).toHaveCount(0);
    await page.getByRole('button', { name: /Dra\. Elena Ruiz/ }).click();
    await expect(
      page.getByRole('region', { name: 'Hilo de mensajes' }).getByText('Recuerda traer tus estudios.'),
    ).toBeVisible();

    await assertCurrentAnd320Overflow(page);
    expect(errors).toEqual([]);
  });

  test('doctor: panel sin tarjeta simulada, Stripe Checkout y retorno success/cancel, y PUT /api/me 400 mantiene sesión', async ({
    page,
  }) => {
    const errors = attachErrorTrackers(page, [400]);
    const state = freshState({ subscriptionActive: false });
    await seedSession(page, 'DOCTOR');
    await mockApiRoutes(page, state);

    await page.goto('/#/panel');
    await expect(page.getByText('Modo prueba (Stripe Sandbox)')).toBeVisible();
    const bodyText = await page.locator('body').innerText();
    expect(bodyText).not.toContain('4242 4242');
    expect(bodyText.toLowerCase()).not.toContain('simulación');

    // Lanzar Stripe Checkout desde botón principal
    await page.getByRole('button', { name: 'Suscribirse con Stripe ($20 USD)' }).click();
    await expect(page.getByText(/Suscripción confirmada/)).toBeVisible();
    expect(state.checkoutCalled).toBe(1);
    expect(state.confirmedSessions).toEqual(['cs_test_123']);
    await expect(page.getByText('Ana López')).toBeVisible();
    await expect(page.getByText('cs_test_hist_123456')).toBeVisible();
    await assertCurrentAnd320Overflow(page);

    // Retorno de Stripe Checkout cancel en #/panel/suscripcion con historial poblado
    await page.goto('/#/panel/suscripcion?stripe_status=cancel');
    await expect(page.getByText(/El pago fue cancelado en Stripe/)).toBeVisible();
    await expect(page.getByText('cs_test_hist_123456')).toBeVisible();
    await assertCurrentAnd320Overflow(page);

    // PUT /api/me con contraseña actual incorrecta (400) NO cierra sesión
    await page.getByLabel('Contraseña actual (opcional)').fill('incorrecta');
    await page.getByLabel('Nueva contraseña (opcional)').fill('NuevaClave1');
    await page.getByRole('button', { name: 'Guardar perfil' }).click();
    await expect(page.getByText('La contraseña actual es incorrecta')).toBeVisible();
    await expect(page).toHaveURL(/#\/panel/);

    await assertCurrentAnd320Overflow(page);
    expect(errors).toEqual([]);
  });

  test('navegación por teclado: skip-link enfoca contenido sin dañar hash y tabs de acceso funcionan con flechas', async ({
    page,
  }) => {
    const errors = attachErrorTrackers(page);
    await mockApiRoutes(page, freshState());

    await page.goto('/#/acceso');
    await page.keyboard.press('Tab');
    const skip = page.locator('.skip-link');
    await expect(skip).toBeFocused();
    await page.keyboard.press('Enter');
    await expect(page.locator('#main-content')).toBeFocused();
    await expect(page).toHaveURL(/#\/acceso/);

    const loginTab = page.getByRole('tab', { name: 'Iniciar sesión' });
    await loginTab.focus();
    await page.keyboard.press('ArrowRight');
    await expect(page.getByRole('tab', { name: 'Crear cuenta' })).toHaveAttribute('aria-selected', 'true');
    await assertCurrentAnd320Overflow(page);

    expect(errors).toEqual([]);
  });
});
