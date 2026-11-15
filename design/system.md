# MiDoc — Sistema de diseño

> **Estado: propuesto, no sincronizado.** El proyecto no tenía tokens: `frontend/src/styles.css` acumula 28 colores hex, 0 custom properties y 5 `!important`. Las filas marcadas **(actual)** provienen de ese CSS; el resto es propuesta de este sistema. Todas las relaciones de contraste están calculadas con la fórmula WCAG 2.x, no estimadas.

## Identidad

**Papel cálido y verde profundo.** La mayoría de los productos de salud se ven como un panel de administración frío: blanco, gris, azul corporativo. MiDoc usa una página color papel (`#f4f2ec`), tinta verde profunda (`#17352b`) y un serif editorial en los títulos. El resultado se lee como un expediente impreso bien cuidado, no como un SaaS más.

Tres reglas de identidad, y sólo tres:

1. **Serif para decir, sans para operar.** Los títulos y las cifras grandes van en serif; toda la interfaz (botones, campos, tablas) en sans. Nunca al revés.
2. **Filete clínico.** La jerarquía se marca con líneas de 1 px y etiquetas en versalitas, no con sombras ni cajas de colores. Una pantalla debe seguir siendo legible impresa en blanco y negro.
3. **El ámbar se gana.** `--color-accent` sólo aparece en foco, cifras que exigen atención y estados que piden una decisión. Si aparece en tres lugares de la misma pantalla, está mal usado.

## Superficies y texto

| Token | Valor | Uso | Origen |
| --- | --- | --- | --- |
| `--color-canvas` | `#f4f2ec` | Fondo de página | nuevo |
| `--color-surface` | `#ffffff` | Tarjetas, paneles, tablas | actual |
| `--color-surface-muted` | `#eae7e0` | Filas alternas, zonas hundidas | nuevo |
| `--color-border` | `#dcd8cf` | Filetes decorativos y separadores (1.29:1, **no** sirve para delimitar controles) | nuevo |
| `--color-border-strong` | `#7d8f86` | Bordes de campos, botones y controles (3.42:1, cumple el mínimo de 3:1 para componentes) | nuevo |
| `--color-text` | `#17352b` | Texto principal (11.87:1 sobre canvas, 13.29:1 sobre blanco) | actual |
| `--color-text-soft` | `#5b7268` | Texto secundario (4.63:1 sobre canvas, 5.18:1 sobre blanco) | actual |
| `--color-text-disabled` | `#9aaba2` | Sólo deshabilitado y placeholder (2.41:1, nunca para texto legible) | actual |
| `--color-text-inverse` | `#ffffff` | Texto sobre superficies oscuras | actual |

## Marca y acento

| Token | Valor | Uso | Origen |
| --- | --- | --- | --- |
| `--color-primary` | `#246b59` | Acción principal, texto blanco encima (6.32:1) | actual |
| `--color-primary-hover` | `#1d5a46` | Hover de la acción principal (8.07:1 con blanco) | actual |
| `--color-primary-active` | `#164a3d` | Estado presionado | actual |
| `--color-primary-soft` | `#d5efe2` | Fondo de apoyo, texto `--color-success` encima (6.64:1) | actual |
| `--color-accent` | `#8a4b00` | Acento escaso: foco alternativo, cifras que importan (6.08:1 sobre canvas) | actual, antes era color de foco |

> `--color-accent` da 1.08:1 sobre `--color-primary`: **nunca** se usa como texto o borde sobre verde.

## Estados

| Token | Valor | Uso | Contraste |
| --- | --- | --- | --- |
| `--color-danger` | `#a83a32` | Error, acción destructiva (texto blanco encima 6.33:1) | 6.33:1 sobre blanco |
| `--color-danger-soft` | `#f8dcd9` | Fondo de error | — |
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
| `--focus-ring` | `2px solid var(--color-focus)` con `outline-offset: 2px` | Único estilo de foco del producto |

Hoy el proyecto tiene **dos colores de foco peleándose** (`styles.css:60` con `#8a4b00` y `app.component.css:37` con `#17352b`). Este sistema deja uno solo. El foco nunca se elimina: si un componente necesita foco propio, redefine `--color-focus`, no `outline: none`.

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

## Radios y medidas

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

## Reglas de componentes

**Botón.** Altura 40 px, padding inline 16 px, radio `--radius-md`, peso 500, `--text-sm`. Variantes: `primary` (fondo `--color-primary`, texto inverso), `secondary` (fondo `--color-surface`, borde `--color-border-strong`, texto `--color-text`), `ghost` (sin borde, hover `--color-surface-muted`), `danger` (fondo `--color-danger`). Deshabilitado: fondo `--color-surface-muted` y texto `--color-text-disabled`; **nunca `opacity`**, porque rompe el contraste y es lo que hace hoy `app.component.css:36`.

**Campo.** Etiqueta visible siempre, encima, `--text-sm`, peso 500. Ayuda en `--color-text-soft`. Error: borde `--color-danger`, texto de error con `role="alert"` y `aria-describedby`. Borde en reposo `--color-border-strong` (3.42:1). El placeholder no reemplaza a la etiqueta.

**Tabla.** `caption` visible o `sr-only`, `th scope="col"`, cifras con `font-variant-numeric: tabular-nums` y alineadas a la derecha. Separación por filete `--color-border`, sin rayado de cebra. Contenedor con scroll horizontal enfocable y `min-width` sólo cuando hace falta.

**Estado (badge).** Píldora `--radius-pill`, fondo `*-soft`, texto `*-` de la misma familia. Se escribe el significado ("Confirmada"), nunca el valor crudo de la base de datos ("CONFIRMADA").

**Diálogo.** `<dialog>` nativo. Foco atrapado, `Esc` cierra, `aria-labelledby` al título, foco devuelto al elemento que lo abrió. Se usa para confirmar acciones destructivas y para explicar consecuencias (revocar consentimiento, borrar un insumo).

**Aviso efímero (toast).** `role="status"`, 6 s, no bloquea, nunca es el único canal de una confirmación importante.

**Pestañas.** `role="tablist"` + `role="tab"` con `aria-selected` y `roving tabindex`, panel con `role="tabpanel"` y `aria-labelledby`. Indicador inferior de 2 px. Hoy son `<button>` sueltos en un `<nav>` con `aria-current`, que no es el patrón.

**Estado vacío.** Título, una frase que explica por qué está vacío y **una** acción primaria. Nunca una pantalla en blanco: hoy "Mis citas" sin citas no ofrece siguiente paso.

**Paginación.** Anterior/siguiente más el rango explícito ("1–20 de 137"). Sin listas infinitas de números.
