# Contexto para retomar (panadería — versión nube)

Léelo junto con `README.md` (bitácora y hoja de ruta). Este archivo solo
resume dónde quedó la última sesión y lo que no es obvio en el código.
Última actualización: 2026-11-13.

## Cómo es el proyecto
- App Streamlit en español para una panadería; base en **Supabase**
  (Postgres), despliegue en **Streamlit Community Cloud** desde la rama
  **`migracion-nube`** (no `main`). Cada push a esa rama actualiza la app.
- La lógica está en módulos (`stock.py`, `pedidos.py`, `recetas.py`, …);
  `app.py` es solo interfaz.
- Responde y escribe en español.

## Dónde quedamos (2026-11-13)
- Se construyó el **stock** (Etapa 4): `stock.py`, sección Stock en la app,
  compras por formato (kg→gr, l→ml), bolsa por receta, descuento al pasar
  un pedido a `en_produccion`, aviso de faltantes. Commit `61b9e0d`,
  esquema `VERSION_ESQUEMA = 4`.
- Ya se hizo push y Streamlit desplegó, pero la primera carga falló con
  `UndefinedTable` (`movimientos_stock`): la migración v4 no corrió porque
  el proceso siguió con el `db.py` viejo. **Solución: "Reboot app"** en
  share.streamlit.io. Si el usuario no confirmó que lo resolvió, empezar
  por ahí (y pedir el log de "Manage app" si persiste).
- **2026-11-17**: el usuario probó Stock y reportó que no podía ingresar
  el empaque (ingrediente/insumo mal modelado). Se agregó
  `ingredientes.categoria` (esquema **v5**), selector Tipo/Categoría en
  Ingredientes → Agregar y Stock → Configurar, y filtros en recetas.
  **Sin commitear ni desplegar todavía** (cambios locales; requiere push
  + "Reboot app"). Quedan por recibir más puntos de su feedback ("1." era
  el primero).
- El usuario va a revisar la funcionalidad y dar retroalimentación. La
  lista de pruebas (13 puntos) se dio en el chat; resumen: Stock (resumen,
  compra, conteo/merma, por reponer, movimientos, configurar), bolsa por
  receta (Recetas → Detalle), y en Pedidos el aviso de faltantes y el
  descuento/devolución de stock.

## Decisiones tomadas (no re-preguntar)
- **Ingrediente** = solo lo que lleva el pan. **Insumo** = todo lo demás
  (`categoria`: empaque, papel, proteccion, limpieza, otro). Las bolsas
  son insumos de categoría `empaque`, unidad `unidad`; cada modelo
  (papel, plástica) es un ítem. Las recetas ofrecen solo ingredientes
  para la fórmula y solo empaques para la bolsa. (Corregido 2026-11-17
  tras feedback: en la v4 "insumo" era una etiqueta sin categorías.)
- Compras del stock **no** generan gasto en Caja: el usuario registra la
  compra completa en Caja y prorratea a mano el precio por gr/ml; en Stock
  ingresa el precio de cada formato.
- Cada receta puede tener su bolsa (`recetas.empaque_ingrediente_id`); su
  precio reemplaza al empaque fijo ($150) de Costos indirectos. Sin bolsa
  asignada se usa el fijo.
- Descuento al pasar a `en_produccion` (cantidad de receta × cantidad del
  ítem + 1 bolsa por pan), una sola vez por pedido; se devuelve si vuelve
  a recibido/confirmado o se elimina el pedido; **cancelar no devuelve**.
  Se permite stock negativo. El aviso de faltantes no bloquea.
- La cantidad por ingrediente en recetas es **por unidad (un pan)**.

## Pendiente
- Anticipar faltantes según los pedidos confirmados de la semana (README,
  Etapa 4).
- Cargar inventario inicial y mínimos (lo hace el usuario en la app).
- Respaldo de Supabase **sin hacer** antes de esta migración: desde la red
  del PC de desarrollo no conecta a Supabase (timeout puertos 5432/6543).
  Hay que correr `respaldos_supabase/respaldo_supabase.py` desde otra red.
- Etapa 3 (3 panificadoras) y siguientes: ver README.

## Trampas conocidas
- Cambios de esquema: subir `VERSION_ESQUEMA` en `db.py` **y** reiniciar
  la app en Streamlit Cloud ("Reboot app"); recargar código no basta.
- Respaldar antes de migrar y ensayar el SQL en `BEGIN … ROLLBACK`.
- En el PC de desarrollo la app **no corre localmente** (Control de
  aplicaciones de Windows bloquea DLL de psycopg2/pandas). Se verifica con
  `py -m py_compile`, pruebas con módulos simulados y SQLite en memoria, y
  la prueba real es en Streamlit Cloud.
- Git: si dice "gitfile does not point to a valid repository", cambió el
  nombre de usuario de Windows; reescribir las rutas en `.git` de este
  worktree y en `../panaderia_sistema/.git/worktrees/panaderia_sistema-nube/gitdir`.
- `.streamlit/secrets.toml` (cadena de conexión) no está en git: en otro
  dispositivo hay que copiarlo aparte o usar los "Secrets" de Streamlit.
