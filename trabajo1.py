# Trabajo Practico Extracción y almacenamiento, Camilo Seifar,  Art Institute of Chicago API

# Reglas de la api: Maximo 60 pedidos por minuto por IP(Usuarios anonimos), Limit = 100, endpoints de busqueda no pueden pasar de 10.000 resultados, para volcados enormes usar data dumps, identificarse con el header AIC-User-Agent, usar fields para pedir solo lo necesario, Si se realiza scraping que sea en un solo hilo y no mas de 1 pedido por segundo.

import time
from pathlib import Path # para los paths de los datos extraidos
import pandas as pd  # DataFrame 
import requests # solicitudes
from deltalake import DeltaTable, write_deltalake # dependencias de deltalake para python, se instalo arrow para usarlos)

BASE_URL = "https://api.artic.edu/api/v1" # la api 
HEADERS = {"AIC-User-Agent": "TP1-DataEngineering-UTN-Camilo-Seifar (camiloseifar@gmail.com)"} # pedido de el ARTIC para usarlo.

PAUSA_SEGUNDOS = 1 # la api pide no superar 1 pedido por segundo
LIMITE_POR_PAGINA = 100 # maximo permitido por la api
MAX_PAGINAS = 50 # Tope de seguridad del incremental
DIAS_PRIMERA_CARGA = 7  # si una tabla no existe se traen los ultimos 7 dias


RUTA_TIPOS = Path("datos/crudo/artic/artwork_types")
RUTA_OBRAS = Path("datos/crudo/artic/artworks")

CAMPOS_OBRAS = (
  "id,title,artist_title,date_display,"
  "artwork_type_title,department_title,updated_at"
)

def pedir_json(endpoint,params):
  """ hacer un get a la api y que devuelva la respuesta como diccionario """
  respuesta = requests.get(
    f"{BASE_URL}/{endpoint}",
    params=params,
    headers=HEADERS, # para que headers del requests.get sepa que tiene que sacar la misma data de mi variable HEADERS.
    timeout=30,  # cuanto espera antes de rendirse, 30 segs
  )
  respuesta.raise_for_status() # corta si la api devolvio un error
  time.sleep(PAUSA_SEGUNDOS) # respetar el limite de los pedidos
  return respuesta.json()

## print(pedir_json("artwork-types", {"limit": 2})) // ejemplo que use para testearla

""" EXTRACCION FULL """
# traer todos los registros de /artwork-types, recorriendo todas las paginas y devolverlos como DataFrame de panda.

def extraer_full(endpoint) :
  registros = []
  pagina = 1
  while True:
    datos = pedir_json(endpoint, {"page": pagina, "limit": LIMITE_POR_PAGINA})
    registros.extend(datos["data"])
    if pagina >= datos["pagination"]["total_pages"]:
      break
    pagina += 1
  print(f"FULL {endpoint}: {len(registros)} registros")
  return pd.DataFrame(registros)

"""Guardar el FULL en Delta Lake """
def guardar_full(df, ruta):
 """Pisa la tabla completa (overwrite)."""
 ruta.mkdir(parents=True, exist_ok=True)
 write_deltalake(str(ruta), df.astype(str), mode="overwrite")
 print(f"Guardado FULL en {ruta} ({len(df)} filas)")

"""watermark: averiguar la fecha de la última obra guardada para pedir solo lo posterior """


def obtener_watermark(ruta):
  """Devuelve la fecha de actualizacion mas reciente ya guardada. """
  if DeltaTable.is_deltatable(str(ruta)):
    guardado =  DeltaTable(str(ruta)).to_pandas(columns=["updated_at"])
    if not guardado.empty:
      return pd.to_datetime(guardado["updated_at"], utc=True).max()
  return pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=DIAS_PRIMERA_CARGA)

""" Extraccion incremental de obras """

def extraer_incremental(endpoint, campos, desde):
    """Trae solo los registros con updated_at posterior a `desde`."""
    registros = []
    for pagina in range(1, MAX_PAGINAS + 1):
        datos = pedir_json(
            endpoint,
            {"page": pagina, "limit": LIMITE_POR_PAGINA, "fields": campos},
        )
        lote = datos["data"]
        nuevos = [
            r for r in lote
            if pd.to_datetime(r["updated_at"], utc=True) > desde
        ]
        registros.extend(nuevos)
        # La API ordena de más nuevo a más viejo: si ya apareció uno viejo, cortamos.
        if not lote or len(nuevos) < len(lote):
            break
    print(f"INCREMENTAL {endpoint}: {len(registros)} registros desde {desde}")
    return pd.DataFrame(registros)

""" Preparar fecha y hora para particionar """

def preparar_particiones(df):
  """ Agrega las columnas fecha y hora (para particionar) y pasa todo a texto."""
  if df.empty:
    return df 
  df = df.copy()
  df["updated_at"] = pd.to_datetime(df["updated_at"], utc=True)
  df["fecha"] = df["updated_at"].dt.strftime("%Y-%m-%d")
  return df.astype(str)   # Todo a texto. updated_at queda como 2026-10-27 14:05:33+00:00

""" Guardar el incremental sin duplicar """

def guardar_incremental(df,ruta):
  """Inserta solo las filas nuevas, sin duplicar."""
  if df.empty:
    print("No hay registros nuevos para guardar") # Avisa con un mensaje y sale con return. No toca la tabla.
    return
  ruta.mkdir(parents=True, exist_ok=True)
  if not DeltaTable.is_deltatable(str(ruta)):
    write_deltalake(str(ruta), df, partition_by=["fecha"]) # La tabla todavía no existe (primera corrida

  else:
    (
      DeltaTable(str(ruta))
      .merge(    # La tabla ya existe
        source=df,
        predicate="t.id = s.id AND t.updated_at = s.updated_at",
        source_alias="s",
        target_alias="t",
      )
      .when_not_matched_insert_all()
      .execute()
    )
  print(f"Guardado INCREMENTAL en {ruta} ({len(df)} filas procesadas)")

def main():
 # 1) Datos estaticos: full + overwrite
  df_tipos = extraer_full("artwork-types")
  guardar_full(df_tipos, RUTA_TIPOS)
 # 2) Datos temporales: incremental + merge particionado
  desde = obtener_watermark(RUTA_OBRAS)
  df_obras = extraer_incremental("artworks", CAMPOS_OBRAS, desde)
  df_obras = preparar_particiones(df_obras)
  guardar_incremental(df_obras, RUTA_OBRAS)

if __name__ == "__main__":
 main()


print("todo joya") # usado para chequear mientras trabajaba de que estaba todo ok