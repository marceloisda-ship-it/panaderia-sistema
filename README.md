# Sistema de Gestión — Panadería

Sistema modular en Python para gestionar el negocio: costeo de recetas,
flujo de caja, pedidos y clientes.

**Estado actual**: los módulos de **Costeo** (ingredientes y recetas),
**Flujo de caja**, **Costos indirectos**, **Pedidos**, **Clientes** y
**Dashboard** ya están funcionando, con una interfaz visual (Streamlit)
para usarlos día a día.

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

1. Creas un **pedido** eligiendo un **cliente** ya registrado, o
   creando uno nuevo ahí mismo sin salir de la pantalla (ver Clientes
   más abajo), y la **fecha de entrega**.
2. Le agregas **ítems**: una o varias recetas, cada una con su cantidad.
   El precio de cada ítem queda "congelado" al momento de agregarlo, así
   que si después cambias el precio de venta de la receta, los pedidos
   ya tomados no se alteran.
3. Al agregar un ítem, el sistema avisa (sin bloquear) si eso sobrepasa
   tu **capacidad de producción** para ese día — ver punto 5.
4. Cuando entregas el pedido y el cliente paga, marcas **"Entregar y
   cobrar"** con el medio de pago: el sistema genera automáticamente el
   ingreso correspondiente en **Flujo de caja**, sin que tengas que
   registrarlo dos veces.
5. La **capacidad de producción diaria** se mide en tiempo, no en
   unidades: defines cuántas horas al día dedicas a producir, y el
   sistema usa el tiempo de preparación por lote que ya cargaste en cada
   receta (mano de obra, ver Costos indirectos) para saber cuánto de esa
   capacidad ya está comprometida en pedidos de un día dado.
6. La pestaña **Planificación** te da la vista para organizarte: un
   gráfico de barras con las unidades pedidas día por día (para ver de
   un vistazo qué días vienen más cargados), y al elegir un día
   puntual, el desglose de **qué panes preparar** (agregado entre todos
   los pedidos de ese día) y el detalle de cada pedido con su cliente.

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
      sobreventa, y cobro que genera el ingreso en Caja automáticamente.
- [x] **Clientes**: ficha de cliente (nombre, teléfono, dirección,
      notas), historial de pedidos, y reportes de inteligencia de negocio
      (quién compra más, qué pan se pide más).
- [x] **Dashboard**: KPIs mensuales de pedidos (por estado, cumplimiento,
      cancelación, ticket promedio), financieros (ingresos, gastos, saldo,
      comisiones) y de rentabilidad (más vendidos vs. más rentables, aviso
      de recetas bajo margen), comparados contra el mes anterior.
- [x] Interfaz visual local (Streamlit), reusando toda la lógica ya
      construida en estos módulos — ver `app.py`.

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
  2. Botón en Pedidos → Detalle/Cobrar que genere un texto-resumen del
     pedido (ítems, total, fecha de entrega) listo para copiar y pegar
     en WhatsApp — sin APIs externas, mejora chica dentro del sistema.
  3. Integración real vía WhatsApp Business Platform (Meta Cloud API):
     mensajes y creación de pedidos automáticos. Implica alojar el
     sistema en un servidor con acceso a internet (hoy corre local) y
     pasar verificación de negocio de Meta — proyecto aparte, no
     iniciar sin que el volumen de pedidos lo justifique.
  4. Automatización avanzada: catálogo interactivo en el chat,
     respuestas automáticas, pagos con link que se registran solos en
     Caja.
