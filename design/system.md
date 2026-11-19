# MiDoc — Sistema de diseño

> **Estado: activo y sincronizado.** La fuente de verdad ejecutable vive en `frontend/src/styles/_tokens.css` y se valida automáticamente en `frontend/src/styles/tokens.spec.ts` (paridad 1:1 de tokens y contraste WCAG 2.x). Todos los textos de producto en la aplicación usan español de México (`es-MX`, trato de «tú»).

## Identidad

**Papel cálido y verde profundo.** La mayoría de los productos de salud se ven como un panel de administración frío: blanco, gris, azul corporativo. MiDoc usa una página color papel (`#f4f2ec`), tinta verde profunda (`#17352b`) y un serif editorial en los títulos. El resultado se lee como un expediente impreso bien cuidado, no como un SaaS genérico.

Tres reglas de identidad, y sólo tres:

1. **Serif para decir, sans para operar.** Los títulos y las cifras grandes van en serif; toda la interfaz (botones, campos, tablas) en sans. Nunca al revés.
2. **Filete clínico.** La jerarquía se marca con líneas de 1 px y etiquetas en versalitas, no con sombras ni cajas de colores. Una pantalla debe seguir siendo legible impresa en blanco y negro.
3. **El ámbar se gana.** `--color-accent` sólo aparece en foco alternativo, cifras que exigen atención y promociones que piden una decisión. Si aparece en tres lugares de la misma pantalla, está mal usado.

## Superficies y texto

| Token | Valor | Uso |
| --- | --- | --- |
| `--color-canvas` | `#f4f2ec` | Fondo de página |
| `--color-surface` | `#ffffff` | Tarjetas, paneles, tablas |
| `--color-surface-muted` | `#eae7e0` | Filas alternas, zonas hundidas, botón deshabilitado |
| `--color-border` | `#dcd8cf` | Filetes decorativos y separadores (1.29:1, **no** sirve para delimitar controles) |
| `--color-border-strong` | `#7d8f86` | Bordes de campos, botones y controles (3.42:1, cumple el mínimo de 3:1 para componentes) |
| `--color-text` | `#17352b` | Texto principal (11.87:1 sobre canvas, 13.29:1 sobre blanco) |
| `--color-text-soft` | `#5b7268` | Texto secundario (4.63:1 sobre canvas, 5.18:1 sobre blanco) |
| `--color-text-disabled` | `#9aaba2` | Sólo deshabilitado y placeholder (2.41:1, nunca para texto legible) |
| `--color-text-inverse` | `#ffffff` | Texto sobre superficies oscuras |
| `--color-backdrop` | `rgba(23, 53, 43, 0.42)` | Velo de fondo en diálogos modales (`::backdrop`) |

## Marca y acento

| Token | Valor | Uso |
| --- | --- | --- |
| `--color-primary` | `#246b59` | Acción principal, texto blanco encima (6.32:1) |
| `--color-primary-hover` | `#1d5a46` | Hover de la acción principal (8.07:1 con blanco) |
| `--color-primary-active` | `#164a3d` | Estado presionado |
| `--color-primary-soft` | `#d5efe2` | Fondo de apoyo, texto `--color-success` encima (6.64:1) |
| `--color-accent` | `#8a4b00` | Acento escaso: promociones, cifras que importan (6.08:1 sobre canvas) |
| `--color-accent-soft` | `#fdf3e4` | Fondo suave de promoción o acento (5.92:1 con `--color-accent`) |

> `--color-accent` da 1.08:1 sobre `--color-primary`: **nunca** se usa como texto o borde sobre verde.

## Estados

| Token | Valor | Uso | Contraste |
| --- | --- | --- | --- |
| `--color-danger` | `#a83a32` | Error, acción destructiva (texto blanco encima 6.33:1) | 6.33:1 sobre blanco |
| `--color-danger-hover` | `#8c2d26` | Hover de acción destructiva | 7.90:1 con blanco |
| `--color-danger-soft` | `#f8dcd9` | Fondo de error | 4.86:1 con `--color-danger` |
| `--color-warning` | `#6b4d00` | Aviso | 7.33:1 sobre `#fff7e5` |
| `--color-warning-soft` | `#fff7e5` | Fondo de aviso | — |
| `--color-info` | `#24427a` | Información | 7.84:1 sobre `#dde6f7` |
| `--color-info-soft` | `#dde6f7` | Fondo informativo | — |
| `--color-success` | `#1d5a46` | Confirmación | 6.64:1 sobre `#d5efe2` |
| `--color-success-soft` | `#d5efe2` | Fondo de confirmación | — |

## Foco

| Token | Valor | Uso |
| --- | --- | --- |
| `--color-focus` | `#17352b` | Anillo de foco (11.87:1 sobre canvas) |
| `--focus-ring` | `2px solid var(--color-focus)` | Único estilo de foco del producto |
| `--focus-offset` | `2px` | Separación uniforme del anillo de foco |

El foco nunca se elimina ni se duplica con distintos colores: todo elemento interactivo usa `outline: var(--focus-ring)` y `outline-offset: var(--focus-offset)`.

## Tipografía

| Token | Valor | Uso |
| --- | --- | --- |
| `--font-display` | `ui-serif, Georgia, "Times New Roman", serif` | Títulos, cifras destacadas |
| `--font-ui` | `system-ui, -apple-system, "Segoe UI", Roboto, Arial, sans-serif` | Toda la interfaz |
| `--font-mono` | `ui-monospace, "Cascadia Mono", Consolas, monospace` | Identificadores, folios de receta |
| `--text-xs` | `0.75rem / 1.4` | Versalitas, metadatos |
| `--text-sm` | `0.8125rem / 1.5` | Etiquetas, celdas, botones |
| `--text-base` | `0.9375rem / 1.6` | Texto corrido |
| `--text-md` | `1.0625rem / 1.6` | Texto destacado, campos de lectura |
| `--text-lg` | `1.25rem / 1.45` | Subtítulos, serif |
| `--text-xl` | `1.5rem / 1.3` | Título de sección, serif |
| `--text-2xl` | `1.875rem / 1.2` | Título de pantalla, serif |
| `--text-3xl` | `2.5rem / 1.1` | Cifra o título de portada, serif |
| `--weight-regular` | `400` | Texto |
| `--weight-medium` | `500` | Etiquetas y botones |
| `--weight-semibold` | `600` | Títulos |
| `--tracking-display` | `-0.01em` | Serif de tamaño grande |
| `--tracking-label` | `0.06em` | Versalitas de etiqueta |

Los interlineados de la escala se publican como tokens para que ningún componente los escriba a mano: `--leading-xs` `1.4`, `--leading-sm` `1.5`, `--leading-base` `1.6`, `--leading-md` `1.6`, `--leading-lg` `1.45`, `--leading-xl` `1.3`, `--leading-2xl` `1.2`, `--leading-3xl` `1.1`.

Base 16 px con cuerpo de 15 px: la densidad de un panel clínico, no la de una landing.

## Espaciado

Escala de 4 px. Nada fuera de la escala.

| Token | Valor | Token | Valor |
| --- | --- | --- | --- |
| `--space-1` | `0.25rem` | `--space-6` | `1.5rem` |
| `--space-2` | `0.5rem` | `--space-8` | `2rem` |
| `--space-3` | `0.75rem` | `--space-10` | `2.5rem` |
| `--space-4` | `1rem` | `--space-12` | `3rem` |
| `--space-5` | `1.25rem` | `--space-16` | `4rem` |
| | | `--space-20` | `5rem` |

## Radios, medidas y capas

| Token | Valor | Uso |
| --- | --- | --- |
| `--radius-sm` | `0.25rem` | Etiquetas, celdas |
| `--radius-md` | `0.5rem` | Botones, campos |
| `--radius-lg` | `0.75rem` | Tarjetas |
| `--radius-xl` | `1.25rem` | Diálogos y paneles flotantes |
| `--radius-pill` | `999px` | Estados y filtros activos |
| `--control-height` | `2.5rem` | Altura mínima de todo control (área táctil de 40 px) |
| `--control-height-sm` | `2rem` | Controles en barra de herramientas |
| `--measure` | `68ch` | Ancho máximo de texto corrido |
| `--container-max` | `72rem` | Ancho máximo de la aplicación |
| `--z-sticky` | `10` | Encabezado o pestañas fijas en móvil |
| `--z-dropdown` | `20` | Menús y panel desplegable de avisos |
| `--z-modal` | `40` | Diálogos modales |
| `--z-toast` | `50` | Avisos efímeros |

## Elevación

Sombras teñidas con el verde de tinta, no negro puro: es lo que separa un producto pulido de uno genérico.

| Token | Valor | Uso |
| --- | --- | --- |
| `--shadow-1` | `0 1px 2px rgba(23,53,43,.06), 0 1px 1px rgba(23,53,43,.04)` | Tarjeta en reposo |
| `--shadow-2` | `0 4px 12px rgba(23,53,43,.08), 0 1px 3px rgba(23,53,43,.06)` | Tarjeta elevada, menú |
| `--shadow-3` | `0 16px 40px rgba(23,53,43,.14), 0 2px 8px rgba(23,53,43,.08)` | Diálogo |

## Movimiento

| Token | Valor | Uso |
| --- | --- | --- |
| `--motion-fast` | `120ms` | Hover, foco |
| `--motion-base` | `200ms` | Apertura de paneles |
| `--motion-slow` | `320ms` | Diálogos |
| `--ease-standard` | `cubic-bezier(.2,.6,.2,1)` | Movimiento general |
| `--ease-entrance` | `cubic-bezier(.16,1,.3,1)` | Entradas |

Con `prefers-reduced-motion: reduce` todas las duraciones pasan a `1ms`. No hay animación que transporte información por sí sola.

## Reglas de componentes (`frontend/src/app/ds/`)

Todos los componentes compartidos se implementan como componentes Angular standalone en `frontend/src/app/ds/` consumiendo exclusivamente variables CSS de `_tokens.css`:

- **`ds-button` (`DsButtonComponent`):** Altura mínima `--control-height` (`40px`) o `--control-height-sm` (`32px`), radio `--radius-md`, peso 500, `--text-sm`. Variantes: `primary`, `secondary`, `ghost`, `danger`. Estado deshabilitado o `loading` con fondo `--color-surface-muted` y texto `--color-text-disabled`, **nunca `opacity`**. Expone `aria-busy` cuando `loading` es verdadero.
- **`ds-card` (`DsCardComponent`):** Tarjeta en `--color-surface` (o `--color-surface-muted`), borde 1 px `--color-border`, radio `--radius-lg`, sombra `--shadow-1`; soporta encabezado (`[dsCardHeader]`), pie (`[dsCardFooter]`), estado `selected` (`--color-primary`) e `interactive`.
- **`ds-badge` (`DsBadgeComponent`):** Píldora `--radius-pill` con punto indicador y familia de color semántica (`neutral`, `success`, `warning`, `info`, `danger`). Traduce estados de base de datos (`CONFIRMADA` -> «Confirmada», `PENDIENTE` -> «Pendiente», `COMPLETADA` -> «Completada», `CANCELADA` -> «Cancelada», `ACTIVA` -> «Activa», `INACTIVA` -> «Vencida», `OTORGADO` -> «Otorgado», `REVOCADO` -> «Revocado») para nunca mostrar enumeraciones crudas.
- **`ds-field` (`DsFieldComponent`) + `dsControl` (`DsControlDirective`):** Etiqueta visible siempre encima (`--text-sm`, peso 500). Ayuda en `--color-text-soft`. Error con borde `--color-danger`, `aria-invalid="true"`, `aria-describedby` y texto `role="alert"`. El placeholder no reemplaza a la etiqueta.
- **`ds-modal` (`DsModalComponent`):** `<dialog>` nativo con `aria-labelledby`, `--radius-xl`, `--shadow-3` y `--z-modal`. Cierra con `Esc` o clic en el fondo (salvo cuando `busy` es verdadero) y devuelve el foco al elemento que lo abrió. Reemplaza por completo `globalThis.confirm()`.
- **`ds-empty-state` (`DsEmptyStateComponent`):** Ilustración lineal decorativa (`aria-hidden="true"`), título serif, explicación concisa y una acción primaria opcional para nunca dejar pantallas en blanco.
- **`ds-skeleton` (`DsSkeletonComponent`):** Bloques de carga con `role="status"`, `aria-live="polite"`, texto `.sr-only` y respeto automático de `prefers-reduced-motion`.
- **`ds-alert-banner` (`DsAlertBannerComponent`):** Franja de aviso (`info`, `success`, `warning`, `danger`) con `role="alert"` para `warning`/`danger` y `role="status"` para `info`/`success`, acción y cierre opcional.
- **`ds-page-header` (`DsPageHeaderComponent`):** Encabezado editorial de sección con `eyebrow`, título serif (`h1` o `h2`), subtítulo y ranura derecha `[dsPageActions]` separada por filete `--color-border`.
- **Tabla clínica:** `caption` visible o `sr-only`, `th scope="col"`, cifras con `font-variant-numeric: tabular-nums`. Separación por filete `--color-border`, sin rayado de cebra. Contenedor `.table-scroll` enfocable.
- **Pestañas:** `role="tablist"` + `role="tab"` con `aria-selected` y `roving tabindex`, o `<nav aria-label="Secciones">` con `routerLinkActive` y `aria-current="page"`.
