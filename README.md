# Sistema de Gestión — Panadería

Sistema modular en Python para gestionar el negocio: costeo de recetas,
flujo de caja, pedidos y clientes.

**Estado actual**: los módulos de **Costeo** (ingredientes y recetas),
**Flujo de caja**, **Costos indirectos**, **Pedidos**, **Clientes** y
**Dashboard** ya están funcionando, con una interfaz visual (Streamlit)
para usarlos día a día. Las Etapas 1 y 2 de la hoja de ruta (flujo de
estados y cobranza) están terminadas; ver **Bitácora de cambios** al
final para el detalle de la última sesión.

**Dónde corre**: la versión en uso vive en la nube — base de datos en
**Supabase** (Postgres, región São Paulo) y app en **Streamlit Community
Cloud**, que despliega la rama `migracion-nube` (no `main`). Cada push a
esa rama actualiza la app. Las secciones de abajo sobre `panaderia.db`
(SQLite) y `main.py` describen la versión local original.

## Cómo ejecutarlo

Requiere Python 3.10+.

### Interfaz visual (recomendada para uso diario)

```bash
cd panaderia_sistema
./iniciar_app.sh
```

La primera vez instala automáticamente las dependencias (`streamlit`,
`pandas`); las siguientes veces solo levanta la app.

Se abre en el navegador (`http://localhost:8501`). Desde ahí puedes
moverte entre los módulos (Ingredientes, Recetas, Flujo de caja) sin
tener que reescribir datos ni perder de vista los resultados.

### Menú de consola (en pausa)

El menú de consola original (`main.py`) sigue funcionando tal cual —
usa las mismas funciones y la misma base de datos — pero no se le
seguirán agregando los módulos nuevos; quedó como respaldo rápido.

```bash
python3 main.py
```

Al ejecutar cualquiera de las dos interfaces por primera vez se crea
automáticamente el archivo `panaderia.db` (base de datos SQLite) en la
misma carpeta. Ahí queda guardada toda la información — puedes copiar
ese archivo como respaldo cuando quieras.

## Estructura del proyecto

```
panaderia_sistema/
├── db.py             # Conexión y esquema de la base de datos
├── ingredientes.py   # Lógica de ingredientes y su historial de precios
├── recetas.py        # Lógica de recetas: costeo automático y margen
├── caja.py               # Lógica de flujo de caja: ingresos, gastos y reportes
├── costos_indirectos.py  # Configuración de luz, empaque y mano de obra
├── produccion.py         # Capacidad de producción diaria (control de sobreventa)
├── pedidos.py             # Pedidos de clientes, ítems y cobro (conecta con Caja)
├── clientes.py             # Ficha de clientes e inteligencia de negocio
├── dashboard.py           # KPIs mensuales: pedidos, ventas y rentabilidad (combina los módulos anteriores)
├── app.py                # Interfaz visual (Streamlit) — módulo activo de UI
├── iniciar_app.sh        # Script para levantar la interfaz visual
├── main.py               # Menú de consola (en pausa, se mantiene como respaldo)
├── requirements.txt      # Dependencias de la interfaz visual
└── panaderia.db          # Se genera automáticamente al ejecutar (no se sube al repo)
```

La lógica de negocio (`db.py`, `ingredientes.py`, `recetas.py`, `caja.py`,
`costos_indirectos.py`, `produccion.py`, `pedidos.py`, `clientes.py`,
`dashboard.py`) es independiente de la interfaz: `app.py` llama a estas
funciones, así que
cualquier módulo nuevo se escribe una sola vez y queda disponible para la
interfaz visual (el menú de consola `main.py` quedó en pausa, ver más
abajo).

## Cómo funciona el costeo

1. Registras tus **ingredientes** con su precio actual por unidad base
   (gramo, mililitro o unidad). Cada vez que actualizas un precio, el
   sistema guarda un historial — así podrás ver la evolución de precios
   en el tiempo.
2. Creas una **receta** (pan) con su precio de venta y el margen de
   ganancia que quieres lograr (ej. 40%).
3. Le agregas los ingredientes de la receta con la cantidad que usa
   (en la misma unidad base del ingrediente).
4. El sistema calcula automáticamente, sumando también los **costos
   indirectos** configurados (ver más abajo):
   - Costo directo (ingredientes)
   - Costo indirecto (luz + empaque + mano de obra de esa receta)
   - Costo total, ganancia (precio de venta − costo total) y margen real (%)
   - Si está **por debajo** del margen objetivo → te avisa

## Cómo funciona el flujo de caja

1. Registras **ingresos** (ventas) y **gastos** (insumos, arriendo,
   servicios, etc.), indicando el **medio de pago** (efectivo, débito
   o transferencia) y, opcionalmente, una categoría y descripción.
2. Cada movimiento queda con su fecha (por defecto, hoy).
3. El **reporte por período** (todo el historial, o un rango de fechas)
   te muestra:
   - Total de ingresos, gastos y saldo del período
   - Desglose por medio de pago (para saber cuánto tienes en efectivo,
     débito y transferencia)
   - Desglose por categoría

## Cómo funcionan los costos indirectos

El costo final de cada receta no es solo la suma de ingredientes — también
incluye tres componentes indirectos, configurables en un solo lugar
(pantalla **Costos indirectos** en la interfaz visual):

1. **Luz**: se configura **por receta**, según el programa de la máquina
   de pan que usa (consumo en kWh). Se multiplica por la tarifa eléctrica
   y por un factor de descuento (configurados una sola vez, para
   compensar que el consumo teórico del programa es un techo — la
   resistencia cicla por termostato y no tira potencia nominal todo el
   ciclo). No se divide por las unidades del lote: cada pan se hornea en
   su propia máquina con su propio ciclo completo, así que no se abarata
   por preparar varios panes en la misma sesión.
2. **Empaque**: un monto fijo (ej. $30) que se suma **igual a todas las
   recetas**, sin tener que asignarlo receta por receta.
3. **Mano de obra**: también se configura **por receta**, porque cada pan
   toma un tiempo distinto de preparar. Le indicas cuántos minutos toma
   la sesión de preparación y cuántas unidades rinde esa sesión; junto
   con el valor de tu hora (configurado una sola vez), se calcula el
   costo de mano de obra específico de esa receta — a diferencia de la
   luz, esta sí se reparte entre las unidades del lote, porque el tiempo
   activo de preparación es compartido.

Hoy el sistema no incluye gas ni arriendo porque, en este negocio, la
maquinaria es eléctrica y no se paga arriendo — la luz es el único costo
fijo relevante. Si eso cambia, se puede ampliar el mismo mecanismo.

## Cómo funcionan los pedidos

Cada pedido avanza por estos estados (el flujo completo está en **Flujo
ideal de un pedido**, más abajo):

`recibido` → `confirmado` → `en producción` → `listo` → `entregado`
(cualquiera de los cuatro primeros puede pasar a `cancelado`)

El **pago va aparte del estado**: un pedido puede estar entregado y
todavía sin pagar (queda **por cobrar**), o pagado por adelantado antes
de entregarse.

La sección **Pedidos** tiene estas pestañas:

1. **Planificación**: **calendario del mes** con los pedidos de cada día
   (un chip de color por estado: 🟡 recibido, 🔵 confirmado, 🟠 en
   producción, 🟣 listo, 🟢 entregado; borde rojo si el día está
   sobrevendido), resumen del mes por estado y cuántos entregados siguen
   sin pagar, **tiempo requerido, disponible y restante** (de hoy en
   adelante), y el detalle de un día: **qué panes preparar** y cada pedido.
2. **Agenda**: pedidos agrupados por fecha de entrega, con filtro de
   fechas y de estado (Recibido, Confirmado, En producción, Listo,
   Entregado — en ese orden; sin cancelados ni "por cobrar"). También
   permite **reagendar de una vez todos los pedidos de un día**.
3. **Crear pedido**: elegir un **cliente** existente o crearlo ahí
   mismo, la **fecha de entrega** y **por dónde llegó** el pedido
   (WhatsApp, presencial, Instagram u otro). El pedido nace `recibido` y
   se le agregan ítems en la misma pantalla.
4. **Agregar ítems**: solo lista pedidos `recibido` y `confirmado`. Orden
   de la pantalla: ítems actuales (tabla y total) → ítem para agregar →
   cantidad → ítem para quitar (pide **confirmación** antes de quitar).
   El precio de cada ítem queda "congelado" al agregarlo. Si un ítem
   sobrepasa la capacidad del día, avisa sin bloquear.
5. **Línea de producción** (antes "Detalle / Cobrar"): todos los pedidos
   agrupados por etapa (Recibido → Entregado; de los entregados, solo los
   de los últimos 14 días; los cancelados no aparecen). Al tocar un
   pedido se despliega todo: datos, ítems, **línea de tiempo** del estado,
   reagendar, registrar pago, cancelar y eliminar.
   - **Línea de tiempo**: muestra los 5 pasos (hechos con ✓, el actual
     destacado, los que faltan en gris). Tocar un paso mueve el pedido a
     ese estado, también hacia atrás para corregir. Tocar **Entregado**
     abre el formulario de entrega: "¿Pagó al recibir?" + medio de pago +
     fecha. Si pagó, se registra el ingreso en Caja en el mismo paso; si
     no, queda por cobrar.
6. **Por cobrar**: entregados sin pagar, del más antiguo al más reciente,
   con los días desde la entrega y el monto adeudado; 🔔 marca los que ya
   pasaron los **días de aviso** (configurables ahí mismo, por defecto 3;
   no es un plazo de pago). Cada uno trae el formulario para registrar el
   pago. Al entrar a Pedidos aparece un aviso si hay cobros que ya toca
   recordar.
7. **Capacidad de producción**: la capacidad diaria se mide en tiempo, no
   en unidades: defines cuántas horas al día dedicas a producir, y el
   sistema usa el tiempo de preparación por lote de cada receta (mano de
   obra, ver Costos indirectos) para saber cuánto ya está comprometido.

**Pago y Caja**: al registrar un pago (al entregar o después) se genera
automáticamente el **ingreso** en Flujo de caja y, si fue con débito o
crédito, un **gasto por la comisión** del medio de pago. Todo va en una
sola transacción: nunca queda un pedido pagado sin su ingreso. Un pedido
pagado no se puede pagar dos veces ni eliminar (hay que anular antes el
ingreso en Caja).

## Cómo funcionan los clientes

1. Cada **cliente** tiene una ficha (nombre, teléfono, dirección,
   notas). Todo pedido pertenece a un cliente de esta ficha — ya no se
   escribe el nombre a mano en cada pedido, así que no se fragmenta ni
   se duplica la información de un mismo cliente por errores de tipeo.
2. La **ficha / historial** de un cliente muestra, calculado
   automáticamente a partir de sus pedidos: cuántos pedidos ha hecho,
   cuánto ha gastado en total (solo lo ya pagado) y cuál es su receta
   favorita.
3. Los **reportes** responden dos preguntas de negocio: qué clientes
   compran más (ranking por total gastado) y qué pan se pide más
   (ranking por unidades pedidas).

## Cómo funciona el dashboard

1. Elige un **mes y año**; el dashboard muestra los KPIs de ese mes
   comparados contra el mes calendario anterior (flechas de variación en
   cada métrica).
2. Un **pedido cuenta para el mes en que se tomó** (su fecha de
   creación), no en el que se entrega — esa segunda fecha es la que ya
   se usa en Pedidos → Planificación para organizar la producción.
3. KPIs de pedidos: total tomados, desglose por estado, tasa de
   cumplimiento (% entregados), tasa de cancelación y ticket promedio.
4. KPIs financieros del mes (reusando Flujo de caja): ingresos, gastos,
   saldo y comisiones pagadas a medios de pago electrónicos.
5. Dos rankings de productos, lado a lado, para una pregunta que
   conviene separar: **qué se vende más** (unidades) vs. **qué deja más
   plata** (ganancia estimada = margen actual × unidades vendidas el
   mes) — no siempre es el mismo pan.
6. Aviso automático si alguna receta activa quedó por debajo de su
   margen objetivo, para detectarlo sin tener que revisar receta por
   receta en el módulo de Recetas.

## Módulos construidos

- [x] **Flujo de caja**: ingresos y gastos, diferenciando medio de pago
      (transferencia, débito, efectivo), con reportes por período.
- [x] **Costos indirectos**: luz (por receta, según programa de la
      máquina), empaque (monto fijo) y mano de obra (por receta, según
      tiempo de preparación) incorporados al costeo de cada receta.
- [x] **Pedidos**: capacidad máxima de producción diaria (basada en
      tiempo), pedidos por cliente con fecha de entrega, aviso de
      sobreventa, flujo de estados (recibido → confirmado → en producción
      → listo → entregado) con canal de origen, y entrega y pago por
      separado: el pago genera el ingreso en Caja automáticamente y los
      entregados sin pagar quedan en la vista **Por cobrar**.
- [x] **Clientes**: ficha de cliente (nombre, teléfono, dirección,
      notas), historial de pedidos, y reportes de inteligencia de negocio
      (quién compra más, qué pan se pide más).
- [x] **Dashboard**: KPIs mensuales de pedidos (por estado, cumplimiento,
      cancelación, ticket promedio), financieros (ingresos, gastos, saldo,
      comisiones) y de rentabilidad (más vendidos vs. más rentables, aviso
      de recetas bajo margen), comparados contra el mes anterior.
- [x] Interfaz visual local (Streamlit), reusando toda la lógica ya
      construida en estos módulos — ver `app.py`.

## Flujo ideal de un pedido (la visión)

Así debería vivir cada pedido de la panadería, de punta a punta. Es la
referencia contra la que se mide todo lo que se construye de aquí en
adelante.

| # | Qué pasa | Estado del pedido |
|---|----------|-------------------|
| 1 | **Recibimos el pedido.** Llega por WhatsApp, en persona o por Instagram: alguien pide un pan para cierta fecha. | `recibido` |
| 2 | **Confirmamos.** Se le envía al cliente un mensaje con el detalle de lo pedido; ese mensaje, tal como está, confirma el pedido. | `confirmado` |
| 3 | **Horneamos.** Se arman las cubetas con los ingredientes y se ponen a hornear. Hay 3 panificadoras: se pueden hacer 3 panes distintos a la vez, o 3 del mismo tipo, según lo que se haya pedido. | `en producción` |
| 4 | **Avisamos que está listo.** Mensaje al cliente: su pedido está listo y nos contactaremos para coordinar la entrega. | `listo` |
| 5 | **Entregamos.** Se marca como entregado. A veces el cliente paga al recibir, a veces queda pendiente. | `entregado` |
| 6 | **Cobranza (solo si no pagó).** Se le envía el detalle del pedido con los medios de pago. No hay plazo fijo de pago, pero se quiere un **recordatorio automático** pasados ciertos días desde la entrega. | `entregado` + por cobrar |

Principios que salen de este flujo:

- **El pago es un eje aparte del estado.** Un pedido puede estar
  `entregado` y todavía sin pagar. Entregar y cobrar no siempre ocurren
  juntos.
- **Delegar al sistema lo repetitivo.** Los mensajes de los pasos 2, 4 y 6
  deben salir solos; la meta es que el sistema haga el trabajo repetitivo
  y la persona solo decida y hornee.
- **El stock se descuenta al hornear (paso 3)**, que es cuando los
  ingredientes se gastan de verdad, y se verifica al confirmar (paso 2).

## Pasos a seguir

Hoja de ruta por etapas, en el orden propuesto. Cada etapa deja algo
usable por sí sola. Se marca con `[x]` a medida que se va completando.

### Etapa 1 — Flujo de estados del pedido

La base de todo lo demás: que el sistema refleje el flujo ideal.

- [x] Estados nuevos: `recibido`, `confirmado`, `en producción`, `listo`,
      `entregado`, `cancelado` (hoy solo existen pendiente, confirmado,
      entregado y cancelado). Revisar si la base tiene restricciones
      sobre los valores permitidos y migrar los pedidos existentes.
- [x] Guardar el **canal de origen** del pedido (WhatsApp, presencial,
      Instagram).
- [x] **Separar entrega de pago.** Hoy `entregar_y_cobrar` hace las dos
      cosas a la vez; debe poder marcarse *entregado* sin pago, y
      registrar el pago después (generando igual el ingreso en Caja y la
      comisión, si aplica).
- [x] Mostrar los estados nuevos en el calendario de Planificación.

### Etapa 2 — Cobranza

- [x] Vista **Por cobrar**: pedidos entregados sin pagar, con los días
      transcurridos desde la entrega y el monto adeudado.
- [x] Configurar **a los cuántos días** se considera que corresponde
      recordar el pago (sin plazo fijo de pago, solo el aviso).
- [x] Reutilizar el mensaje de recordatorio de pago que ya existe
      (detalle del pedido y medios de pago). *Nota (2026-11-04): el
      mensaje se construyó, pero después se sacaron de la interfaz todos
      los mensajes de WhatsApp porque no se estaban usando. El texto
      sigue en `pedidos.generar_recordatorio_pago_whatsapp` para la
      Etapa 5.*

### Preguntas abiertas antes de las Etapas 3 y 4

Quedaron planteadas y **sin respuesta todavía**; hay que resolverlas al
retomar:

- **Etapa 3**: ¿cada receta ocupa una panificadora durante todo su ciclo
  (o sea, capacidad = 3 tandas en paralelo durante las horas del día), o
  las máquinas son distintas entre sí (programas, tamaños)?
- **Etapa 4**: ¿el stock incluye insumos (bolsas, etiquetas, cajas)? ¿Cómo
  se ingresan las compras (ej. un saco de 25 kg convertido a gramos)?
- Etapa 3 ya tiene una base: la **Línea de producción** (ver Cómo
  funcionan los pedidos) permite pasar pedidos a `en producción` y
  `listo`; falta la asignación por máquina y el nuevo modelo de capacidad.

### Etapa 3 — Producción con 3 panificadoras

- [ ] Revisar el modelo de capacidad: hoy se mide en horas por día;
      con 3 máquinas, cada una con su ciclo, conviene reflejar que se
      pueden hornear hasta 3 tandas en paralelo.
- [ ] Vista de producción del día: qué va en cada máquina, y poder pasar
      los pedidos a `en producción` y luego a `listo`.

### Etapa 4 — Stock

Detalle de lo conversado, para cuando llegue su turno:

- [ ] Cantidad actual y **mínimo** por ingrediente, con tres estados:
      hay / queda poco / sin stock.
- [ ] Stock por **movimientos** (compra, uso, ajuste por merma o
      conteo), no editando el número a mano.
- [ ] Vista **Por reponer**: lo que está bajo el mínimo, agrupado por
      proveedor, con costo estimado según el último precio.
- [ ] Descontar automáticamente al pasar un pedido a `en producción`,
      según la receta.
- [ ] Avisar al confirmar un pedido si faltan ingredientes.
- [ ] Más adelante: anticipar faltantes según los pedidos confirmados
      de la semana.
- Por definir: si se incluyen insumos (bolsas, etiquetas, cajas) y cómo
  se ingresan las compras (ej. un saco de 25 kg convertido a gramos).

### Etapa 5 — Mensajes automáticos por WhatsApp

Objetivo: que los mensajes de confirmación, "pedido listo" y cobranza
salgan solos. Usa la WhatsApp Business Platform (Meta Cloud API); lo
que hay que resolver antes:

- [ ] Verificación del negocio en Meta y número dedicado.
- [ ] **Plantillas de mensaje aprobadas** por Meta (los mensajes que el
      negocio inicia fuera de la ventana de 24 horas requieren plantilla).
- [ ] Un envío automático ligado a los cambios de estado (confirmado,
      listo) y un proceso programado diario para los recordatorios de
      cobranza (ya se usa GitHub Actions para el keepalive; podría
      servir también aquí).
- [ ] Si se quiere recibir mensajes (crear pedidos desde el chat), hace
      falta además un servicio que reciba los avisos de Meta, algo que
      Streamlit por sí solo no hace.

### Etapa 6 — Google Calendar

- [ ] Exportar los pedidos al calendario del emprendimiento (un evento
      por pedido, o uno por día con el resumen), actualizándolo al
      reagendar o cancelar. Solo exportar; sincronizar en ambos
      sentidos queda descartado por ahora.

### Etapa 7 — Recepción automática de pedidos

- [ ] Registrar pedidos que llegan por WhatsApp o Instagram sin tener
      que digitarlos a mano. Depende de la Etapa 5 y se evalúa cuando
      el volumen lo justifique.

## Ideas para más adelante

- Afinar el factor de descuento de luz (hoy en 65%, provisional) con una
  lectura real de consumo eléctrico (medidor enchufable), en vez del
  estimado teórico por programa.
- Dashboard: KPIs de clientes (nuevos vs. recurrentes, riesgo de
  abandono) y de capacidad de producción (% de días sobrevendidos,
  recetas activas sin tiempo de preparación cargado) — quedaron fuera
  de la primera versión a propósito, para no saturar de métricas con
  todavía poca historia de datos.
- **Canal de comunicación por WhatsApp Business**, a construir por etapas:
  1. *(ya en curso)* Solo la app nativa de WhatsApp Business — catálogo
     de productos replicado a mano, mensajes rápidos, mensaje de
     ausencia. Los pedidos se siguen registrando a mano en el sistema.
  2. Textos listos para copiar y pegar en WhatsApp (resumen, pedido
     listo, cobro, recordatorio, datos de transferencia) con botón
     "Abrir en WhatsApp". *Se construyó y se retiró de la interfaz el
     2026-11-04 porque no se usaba; el código sigue en `pedidos.py` y
     `whatsapp.py`.*
  3. Integración real vía WhatsApp Business Platform (Meta Cloud API):
     mensajes y creación de pedidos automáticos. Implica alojar el
     sistema en un servidor con acceso a internet (la versión nube ya
     lo cumple) y pasar verificación de negocio de Meta. Ahora es parte
     de la hoja de ruta: ver **Pasos a seguir → Etapa 5**.
  4. Automatización avanzada: catálogo interactivo en el chat,
     respuestas automáticas, pagos con link que se registran solos en
     Caja.

## Bitácora de cambios

Registro de lo hecho en cada sesión, para retomar sin perder contexto.

### 2026-11-04 — Etapas 1 y 2, y rediseño de Pedidos

**Lo que se construyó** (todo desplegado en `migracion-nube`):

1. **Flujo de estados** (Etapa 1): `recibido`, `confirmado`,
   `en_produccion`, `listo`, `entregado`, `cancelado`. En código las
   claves van sin tilde ni espacio (`en_produccion`); en pantalla se usan
   las etiquetas de `pedidos.ETIQUETAS_ESTADO`. `pedidos.SIGUIENTE_ESTADO`
   define el paso natural siguiente y `ESTADOS_ABIERTOS` los que aún se
   pueden editar, reagendar o cancelar.
2. **Canal de origen** al crear el pedido (`pedidos.CANALES_VALIDOS`).
3. **Entrega y pago separados**: `marcar_entregado()`, `registrar_pago()`
   (también sirve para pago por adelantado) y `entregar_y_cobrar()` como
   atajo que hace ambas cosas en una sola transacción.
   `actualizar_estado()` no acepta `entregado` (obliga a pasar por la
   entrega, que guarda la fecha) y permite volver atrás entre estados
   abiertos.
4. **Cobranza** (Etapa 2): vista Por cobrar, `listar_por_cobrar()`,
   tabla `configuracion_cobranza` (días de aviso, por defecto 3) y aviso
   al entrar a Pedidos.
5. **Interfaz de Pedidos rediseñada**, a pedido del usuario:
   - "Detalle / Cobrar" pasó a ser **Línea de producción** (pedidos
     agrupados por etapa, se despliegan al tocarlos).
   - **Línea de tiempo clickeable** para cambiar el estado (componente
     propio, ver notas técnicas). Reemplazó al botón "avanzar" y al
     "Corregir estado".
   - Filtro de estado solo con los 5 pasos en orden del flujo (se
     quitaron "(todos)", "Abiertos (sin entregar)", "Cancelado" y "Por
     cobrar": el usuario no los encontraba claros).
   - Agregar ítems: solo pedidos recibidos/confirmados, nuevo orden de
     pantalla y confirmación antes de quitar un ítem.
   - **Se retiraron de la interfaz todos los mensajes de WhatsApp**
     (resúmenes, recordatorios, datos de transferencia, botones wa.me,
     envíos automáticos e historial) porque no se usaban. Las funciones
     siguen en `pedidos.py` (`generar_*_whatsapp`) y `whatsapp.py`.

**Base de datos (Supabase)**:

- Columnas nuevas en `pedidos`: `canal_origen`, `fecha_entregado`,
  `fecha_pago`. Tabla nueva `configuracion_cobranza`.
- El CHECK `pedidos_estado_check` ahora acepta los 6 estados nuevos; el
  valor por defecto es `recibido`.
- Migración aplicada el 2026-11-04: no había pedidos `pendiente`; los 47
  entregados (todos pagados) recibieron `fecha_entregado` y `fecha_pago`
  = su `fecha_entrega` como aproximación. En ese momento: 54 pedidos
  (5 confirmados, 47 entregados, 2 cancelados) y 0 por cobrar.
- **Respaldo** previo en
  `La PanaderIA/respaldos_supabase/2026-11-04_1856/` (fuera del repo:
  contiene datos de clientes). Para repetirlo: `respaldo_supabase.py` en
  esa carpeta (ver notas técnicas).

**Commits del día**: `579b9f4`, `8dacbc9`, `b2d7f49`, `2e3a9e6`,
`e59d0b8`, `6464a78`, `4b7c908`, `cfdefc3`, `1f31c61`.

**Pendiente de verificar en la app** (no se pudo probar en el PC de
desarrollo, ver notas técnicas): cómo se ve la línea de tiempo en el
celular, los clics de la línea de tiempo y el diálogo de confirmación al
quitar un ítem.

**Siguiente paso**: responder las **Preguntas abiertas antes de las
Etapas 3 y 4** (sección Pasos a seguir) y seguir con la Etapa 3.

### Notas técnicas para retomar

- **Cambios de esquema**: `db.inicializar_db()` crea las tablas y aplica
  migraciones idempotentes. Al cambiar el esquema **hay que subir
  `VERSION_ESQUEMA` en `db.py`**: Streamlit Cloud, al recibir un push,
  recarga el código sin reiniciar el proceso y conserva el
  `st.cache_resource`, así que sin subir la versión la migración no corre
  (pasó el 2026-11-04: la app falló con `UndefinedColumn
  fecha_entregado` y hubo que aplicar la migración a mano).
- **Antes de migrar**: respaldar y ensayar el SQL contra Supabase dentro
  de `BEGIN … ROLLBACK`.
- **PC de desarrollo**: el Control de aplicaciones de Windows bloquea las
  DLL de `psycopg2` y `pandas`, así que la app **no corre localmente**
  (ni con `streamlit run` ni con `AppTest`). Para revisar el código se
  usa `py -m pyflakes` y pruebas con módulos simulados; la prueba real es
  en Streamlit Cloud. Para conectarse a Supabase desde el PC se usa
  `pg8000` (Python puro) verificando TLS con la CA raíz de Supabase
  (`prod-ca-2021.crt`).
- **Línea de tiempo**: `linea_tiempo_pedido()` en `app.py`, hecha con
  `st.components.v2.component` (HTML/CSS/JS en línea). Al tocar un paso,
  el JS envía la clave del estado con `setTriggerValue("elegido", …)`.
  Los formularios de entrega abiertos se guardan en
  `st.session_state["entregar_pedido_id"]` (un conjunto de ids).
- **Línea de producción**: cada pedido es un `st.expander` con
  `key=f"exp_pedido_{id}"` y `on_change="rerun"`; el detalle solo se arma
  si `exp.open`, para no hacer lenta la pantalla. Todas las claves de
  widgets del detalle llevan el id del pedido (se pueden abrir varios).
- **Git en este PC**: si git dice "gitfile does not point to a valid
  repository", es porque cambió el nombre de la carpeta de usuario de
  Windows; hay que reescribir las rutas en `.git` de este worktree y en
  `../panaderia_sistema/.git/worktrees/panaderia_sistema-nube/gitdir`.
