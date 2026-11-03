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
  respuesta.raise_for_status # corta si la api devolvio un error
  time.sleep(PAUSA_SEGUNDOS) # respetar el limite de los pedidos
  return respuesta.json()

## print(pedir_json("artwork-types", {"limit": 2})) // ejemplo que use para testearla

""" EXTRACCION FULL """
# traer todos los registros de /artwork-types, recorriendo todas las paginas y devolverlos como DataFrame de panda.



print("todo joya") # usado para chequear mientras trabajaba de que estaba todo ok