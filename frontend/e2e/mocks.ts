import { expect, Page } from '@playwright/test';

export interface MockApiState {
  failDoctorsOnce?: boolean;
  doctorsDelayMs?: number;
  emptyDoctors?: boolean;
  emptySlots?: boolean;
  confirmedSessions: string[];
  checkoutCalled: number;
  subscriptionActive: boolean;
}

export function attachErrorTrackers(page: Page, expectedHttpErrors: number[] = []): string[] {
  const errors: string[] = [];
  page.on('console', (msg) => {
    if (msg.type() === 'error') {
      const text = msg.text();
      const isExpectedHttp = expectedHttpErrors.some((status) =>
        text.includes(`status of ${status}`),
      );
      if (!isExpectedHttp) {
        errors.push(`console.error: ${text}`);
      }
    }
  });
  page.on('pageerror', (err) => {
    errors.push(`pageerror: ${err.message}`);
  });
  return errors;
}

export async function assertNoHorizontalOverflow(page: Page): Promise<void> {
  const overflow = await page.evaluate(() => {
    const docOverflow = document.documentElement.scrollWidth > window.innerWidth + 1;
    const offending: string[] = [];
    for (const el of Array.from(document.querySelectorAll('*'))) {
      if (el.closest('.table-scroll')) continue;
      const rect = el.getBoundingClientRect();
      if (rect.width > 0 && rect.right > window.innerWidth + 1.5) {
        offending.push(`${el.tagName}.${el.className}: right=${Math.round(rect.right)} > ${window.innerWidth}`);
      }
    }
    return { docOverflow, offending };
  });
  expect(overflow.docOverflow, `Overflow horizontal: ${overflow.offending.join(', ')}`).toBe(false);
  expect(overflow.offending).toEqual([]);
}

export async function seedSession(
  page: Page,
  role: 'PACIENTE' | 'DOCTOR',
  name = role === 'DOCTOR' ? 'Dr. Sol' : 'Ana López',
): Promise<void> {
  const user =
    role === 'DOCTOR'
      ? { id: 'u-doc-1', email: 'doc@midoc.mx', role: 'DOCTOR', name, doctorId: 'doc-1' }
      : { id: 'u-pat-1', email: 'ana@midoc.mx', role: 'PACIENTE', name };
  await page.addInitScript((session) => {
    localStorage.setItem('midoc.session', JSON.stringify(session));
  }, { token: 'jwt-e2e-token', user });
}

export async function mockApiRoutes(page: Page, state: MockApiState): Promise<void> {
  const futureIso = new Date(Date.now() + 86_400_000 * 3).toISOString();

  await page.route('http://localhost:3000/api/**', async (route) => {
    const req = route.request();
    const url = new URL(req.url());
    const path = url.pathname;
    const method = req.method();

    const json = (data: unknown, status = 200) =>
      route.fulfill({
        status,
        contentType: 'application/json',
        body: JSON.stringify(data),
      });

    if (path === '/api/doctors' && method === 'GET') {
      if (state.doctorsDelayMs) {
        await new Promise((r) => setTimeout(r, state.doctorsDelayMs));
      }
      if (state.failDoctorsOnce) {
        state.failDoctorsOnce = false;
        return json({ error: 'Servicio temporalmente no disponible' }, 503);
      }
      if (state.emptyDoctors || url.searchParams.get('q') === 'inexistente') {
        return json({ data: [] });
      }
      return json({
        data: [
          {
            id: 'doc-1',
            userId: 'u-doc-1',
            name: 'Dra. Elena Ruiz',
            specialty: 'Medicina familiar',
            location: 'Av. Vallarta 120',
            city: 'Guadalajara',
            price: 1000,
            durationMin: 30,
            type: 'DOCTOR',
            promotions: [
              {
                id: 'promo-1',
                title: 'Consulta inicial',
                description: 'Aplica en primera visita',
                discountPercent: 20,
                start: '2026-11-01',
                end: '2026-12-31',
                active: true,
              },
            ],
            promotionSummary: {
              count: 1,
              maxDiscountPercent: 20,
              title: 'Consulta inicial',
              discountedPrice: 800,
            },
            nextAvailableSlot: futureIso,
          },
        ],
      });
    }

    if (path === '/api/doctors/doc-1' && method === 'GET') {
      return json({
        data: {
          id: 'doc-1',
          userId: 'u-doc-1',
          name: 'Dra. Elena Ruiz',
          specialty: 'Medicina familiar',
          location: 'Av. Vallarta 120',
          city: 'Guadalajara',
          price: 1000,
          durationMin: 30,
          type: 'DOCTOR',
          schedule: [{ dia_semana: 1, hora_inicio: '09:00', hora_fin: '13:00' }],
          promotions: [],
        },
      });
    }

    if (path === '/api/doctors/doc-1/availability' && method === 'GET') {
      return json({
        data: {
          doctorId: 'doc-1',
          date: url.searchParams.get('date'),
          durationMin: 30,
          slots: state.emptySlots ? [] : [futureIso],
        },
      });
    }

    if (path === '/api/appointments' && method === 'GET') {
      return json({
        data: [
          {
            id: 'cita-1',
            patientId: 'u-pat-1',
            doctorId: 'doc-1',
            dateTime: futureIso,
            status: 'CONFIRMADA',
            reason: 'Chequeo general',
            patientName: 'Ana López',
            doctorName: 'Dra. Elena Ruiz',
            specialty: 'Medicina familiar',
          },
        ],
      });
    }

    if (path.match(/^\/api\/appointments\/[^/]+\/status$/) && method === 'PUT') {
      return json({ data: { id: 'cita-1', status: 'CANCELADA' } });
    }

    if (path === '/api/records' && method === 'GET') {
      return json({
        data: {
          patient_id: 'u-pat-1',
          allergies: ['Polen'],
          notes: 'Sin antecedentes relevantes',
          birthDate: '1994-05-10',
          sex: 'FEMENINO',
          bloodType: 'O+',
          chronicConditions: [],
          medications: [],
          patient: { id: 'u-pat-1', name: 'Ana López', email: 'ana@midoc.mx' },
          consultations: [
            {
              prescriptionId: 'rx-1',
              appointmentId: 'cita-past',
              dateTime: '2026-10-15T16:00:00Z',
              doctorName: 'Dra. Elena Ruiz',
              specialty: 'Medicina familiar',
              diagnosis: 'Rinitis alérgica',
              treatment: 'Lavado nasal diario',
            },
          ],
        },
      });
    }

    if (path === '/api/records/documents' && method === 'GET') {
      return json({
        data: [
          {
            id: 'file-1',
            name: 'biometria.pdf',
            contentType: 'application/pdf',
            size: 15400,
            lastModified: '2026-11-10T10:00:00Z',
            downloadUrl: 'https://example.com/biometria.pdf',
          },
        ],
      });
    }

    if (path === '/api/records/documents/file-1' && method === 'DELETE') {
      return json({ data: { deleted: true } });
    }

    if (path === '/api/records/access-log' && method === 'GET') {
      return json({
        data: [
          {
            id: 'log-1',
            actorId: 'u-doc-1',
            actorName: 'Dra. Elena Ruiz',
            actorRole: 'DOCTOR',
            specialty: 'Medicina familiar',
            event: 'VER_EXPEDIENTE',
            accessedAt: '2026-11-12T15:30:00Z',
          },
        ],
      });
    }

    if (path === '/api/consents' && method === 'GET') {
      return json({
        data: [
          {
            doctorId: 'doc-1',
            doctorName: 'Dra. Elena Ruiz',
            specialty: 'Medicina familiar',
            granted: true,
            updatedAt: '2026-11-01T10:00:00Z',
          },
        ],
      });
    }

    if (path === '/api/messages' && method === 'GET') {
      return json({
        data: [
          {
            userId: 'u-doc-1',
            name: 'Dra. Elena Ruiz',
            lastMessage: 'Recuerda traer tus estudios.',
            updatedAt: '2026-11-18T10:00:00Z',
            unread: 1,
          },
        ],
      });
    }

    if (path === '/api/messages/u-doc-1' && method === 'GET') {
      return json({
        data: [
          {
            id: 'msg-1',
            senderId: 'u-doc-1',
            recipientId: 'u-pat-1',
            content: 'Recuerda traer tus estudios.',
            createdAt: '2026-11-18T10:00:00Z',
            read: true,
          },
        ],
      });
    }

    if (path === '/api/notifications' && method === 'GET') {
      return json({ data: [] });
    }

    if (path === '/api/me' && method === 'GET') {
      return json({
        data: {
          id: 'u-doc-1',
          email: 'doc@midoc.mx',
          role: 'DOCTOR',
          name: 'Dr. Sol',
          phone: '3312345678',
          doctorId: 'doc-1',
          doctor: {
            id: 'doc-1',
            name: 'Dr. Sol',
            specialty: 'Medicina familiar',
            location: 'Av. Reforma 100',
            city: 'CDMX',
            price: 600,
            durationMin: 30,
            schedule: [{ dia_semana: 1, hora_inicio: '09:00', hora_fin: '13:00' }],
          },
          subscription: {
            status: state.subscriptionActive ? 'ACTIVA' : 'INACTIVA',
            amount: 20,
            start: '2026-11-01',
            end: '2026-12-01',
            cardBrand: 'visa',
            cardLast4: '4242',
            active: state.subscriptionActive,
          },
        },
      });
    }

    if (path === '/api/me' && method === 'PUT') {
      const body = req.postDataJSON() as { currentPassword?: string } | null;
      if (body?.currentPassword === 'incorrecta') {
        return json({ error: 'La contraseña actual es incorrecta' }, 400);
      }
      return json({ data: { id: 'u-doc-1', email: 'doc@midoc.mx', role: 'DOCTOR', name: 'Dr. Sol', doctorId: 'doc-1' } });
    }

    if (path === '/api/subscriptions' && method === 'GET') {
      return json({
        data: {
          subscription: state.subscriptionActive
            ? {
                status: 'ACTIVA',
                amount: 20,
                start: '2026-11-01',
                end: '2026-12-01',
                cardBrand: 'visa',
                cardLast4: '4242',
                paymentRef: 'cs_test_hist',
                paymentMode: 'test',
                active: true,
              }
            : null,
          paymentMode: 'test',
          history: [
            {
              id: 'sub-hist-1',
              status: 'ACTIVA',
              amount: 20,
              start: '2026-10-01',
              end: '2026-11-01',
              cardBrand: 'visa',
              cardLast4: '4242',
              paymentRef: 'cs_test_hist_123456',
              paymentMode: 'test',
              active: false,
            },
          ],
        },
      });
    }

    if (path === '/api/subscriptions/checkout' && method === 'POST') {
      state.checkoutCalled += 1;
      return json(
        {
          data: {
            sessionId: 'cs_test_123',
            checkoutUrl: 'http://127.0.0.1:4200/#/panel/suscripcion?stripe_status=success&session_id=cs_test_123',
            mode: 'test',
            amountUsd: 20,
          },
        },
        201,
      );
    }

    if (path === '/api/subscriptions/confirm' && method === 'POST') {
      const body = req.postDataJSON() as { sessionId?: string };
      if (body?.sessionId) state.confirmedSessions.push(body.sessionId);
      state.subscriptionActive = true;
      return json({
        data: {
          subscription: { status: 'ACTIVA', amount: 20, start: '2026-11-18', end: '2026-12-18', active: true },
          payment: { cardBrand: 'visa', cardLast4: '4242' },
        },
      });
    }

    if (path === '/api/doctor/patients' && method === 'GET') {
      return json({
        data: [
          {
            patientId: 'u-pat-1',
            name: 'Ana López',
            email: 'ana@midoc.mx',
            accessSince: '2026-11-01T10:00:00Z',
          },
        ],
      });
    }

    if (path === '/api/doctor/inventory' && method === 'GET') {
      return json({ data: [{ id: 'inv-1', name: 'Guantes', quantity: 10, unit: 'cajas' }] });
    }

    if (path === '/api/doctor/promotions' && method === 'GET') {
      return json({ data: [] });
    }

    return json({ data: [] });
  });
}
