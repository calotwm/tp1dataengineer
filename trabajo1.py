"""Trabajo Practico Extracción y almacenamiento, Camilo Seifar,  Art Institute of Chicago API
Elegi esta API porque no necesita autenticacion, esta bien documentada y tiene todo lo que necesito para el trabajo, ej los endpoints:
- /artworks (temporal) -> extracción INCREMENTAL, merge, partición por fecha.
- /artwork-types (estático) -> extracción FULL, overwrite.

Reglas de la api: Maximo 60 pedidos por minuto por IP(Usuarios anonimos), Limit = 100, endpoints de busqueda no pueden pasar de 10.000 resultados, para volcados enormes usar data dumps, identificarse con el header AIC-User-Agent, usar fields para pedir solo lo necesario, Si se realiza scraping que sea en un solo hilo y no mas de 1 pedido por segundo.

"""

import subprocess
import sys
import time
from pathlib import Path  # para los paths de los datos extraidos
import pandas as pd  # DataFrame
import requests  # solicitudes
from deltalake import (
    DeltaTable,
    write_deltalake,
)  # dependencias de deltalake para python, se instalo arrow para usarlos)

BASE_URL = "https://api.artic.edu/api/v1"  # la api
HEADERS = {
    "AIC-User-Agent": "TP1-DataEngineering-UTN-Camilo-Seifar (camiloseifar@gmail.com)"
}  # pedido de el ARTIC para usarlo.

PAUSA_SEGUNDOS = 1  # la api pide no superar 1 pedido por segundo
LIMITE_POR_PAGINA = 100  # maximo permitido por la api
MAX_PAGINAS = 50  # Tope de seguridad del incremental
DIAS_PRIMERA_CARGA = 7  # si una tabla no existe se traen los ultimos 7 dias


RUTA_TIPOS = Path("datos/crudo/artic/artwork_types")
RUTA_OBRAS = Path("datos/crudo/artic/artworks")

CAMPOS_OBRAS = (
    "id,title,artist_title,date_display,"
    "artwork_type_title,department_title,updated_at"
)


def pedir_json(endpoint, params):
    """hacer un get a la api y que devuelva la respuesta como diccionario"""
    respuesta = requests.get(
        f"{BASE_URL}/{endpoint}",
        params=params,
        headers=HEADERS,  # para que headers del requests.get sepa que tiene que sacar la misma data de mi variable HEADERS.
        timeout=30,  # cuanto espera antes de rendirse, 30 segs
    )
    respuesta.raise_for_status()  # corta si la api devolvio un error
    time.sleep(PAUSA_SEGUNDOS)  # respetar el limite de los pedidos
    return respuesta.json()


## print(pedir_json("artwork-types", {"limit": 2})) // ejemplo que use para testearla

""" EXTRACCION FULL """
# traer todos los registros de /artwork-types, recorriendo todas las paginas y devolverlos como DataFrame de panda.


def extraer_full(endpoint):
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
    """Devuelve la fecha de actualizacion mas reciente ya guardada."""
    if DeltaTable.is_deltatable(str(ruta)):
        guardado = DeltaTable(str(ruta)).to_pandas(columns=["updated_at"])
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
        nuevos = [r for r in lote if pd.to_datetime(r["updated_at"], utc=True) > desde]
        registros.extend(nuevos)
        # La API ordena de más nuevo a más viejo: si ya apareció uno viejo, cortamos.
        if not lote or len(nuevos) < len(lote):
            break
    print(f"INCREMENTAL {endpoint}: {len(registros)} registros desde {desde}")
    return pd.DataFrame(registros)


""" Preparar fecha y hora para particionar """


def preparar_particiones(df):
    """Agrega las columnas fecha y hora (para particionar) y pasa todo a texto."""
    if df.empty:
        return df
    df = df.copy()
    df["updated_at"] = pd.to_datetime(df["updated_at"], utc=True)
    df["fecha"] = df["updated_at"].dt.strftime("%Y-%m-%d")
    return df.astype(
        str
    )  # Todo a texto. updated_at queda como 2026-10-27 14:05:33+00:00


""" Guardar el incremental sin duplicar """


def guardar_incremental(df, ruta):
    """Inserta solo las filas nuevas, sin duplicar."""
    if df.empty:
        print(
            "No hay registros nuevos para guardar"
        )  # Avisa con un mensaje y sale con return. No toca la tabla.
        return
    ruta.mkdir(parents=True, exist_ok=True)
    if not DeltaTable.is_deltatable(str(ruta)):
        write_deltalake(
            str(ruta), df, partition_by=["fecha"]
        )  # La tabla todavía no existe (primera corrida

    else:
        (
            DeltaTable(str(ruta))
            .merge(  # La tabla ya existe
                source=df,
                predicate="t.id = s.id AND t.updated_at = s.updated_at",
                source_alias="s",
                target_alias="t",
            )
            .when_not_matched_insert_all()
            .execute()
        )
    print(f"Guardado INCREMENTAL en {ruta} ({len(df)} filas procesadas)")


def contar_filas(ruta):
    """Cantidad de filas de una tabla Delta (evidencia de que no duplica)."""
    return len(DeltaTable(str(ruta)).to_pandas())


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
    main()  # hace que main() se ejecute solo si corrés este archivo directamente, y no si alguien lo importa desde otro.

""" Tiempo de limpieza y procesamiento """

# lectura del crudo

RUTA_OBRAS_LIMPIAS = Path("datos") / "procesado" / "artic" / "obras_limpias"
RUTA_RESUMEN_DEPTO = (
    Path("datos") / "procesado" / "artic" / "resumen_por_departamento"
)  # en el museo hay varios departamentos de curaduria segun el tipo de obra y su origen.
RUTA_RESUMEN_TIPO = Path("datos") / "procesado" / "artic" / "resumen_por_tipo"

# Textos que significan "no hay dato" y deben pasar a ser nulos reales

VALORES_NULOS = ["None", "none", "nan", "NaN", "<NA>", "null", ""]
ARTISTA_DESCONOCIDO = "Artista desconocido"
VALORES_POR_DEFECTO = {
    "title": "sin titulo",
    "artist_title": ARTISTA_DESCONOCIDO,
    "department_title": "Sin departamento",
    "artwork_type_title": "Sin tipo",
}
RENOMBRAR_OBRAS = {
    "id": "id_obra",
    "title": "titulo",
    "artist_title": "artista",
    "date_display": "fecha_texto",
    "artwork_type_title": "tipo_obra",
    "department_type_title": "departamento",
    "updated_at": "actualizado_en",
}


def leer_delta(ruta, columnas=None):
    """Lee una tabla Delta como Dataframe: Avisa claro si todavia no existe"""
    if not DeltaTable.is_deltatable(str(ruta)):
        raise FileNotFoundError(f"No hay tabla Delta en {ruta}: falta extraer.")
    return DeltaTable(str(ruta)).to_pandas(columns=columnas)


def perfilar(df, nombre):
    """Diagnostico rapido: filas, ids repetidos y cantidad de nulos por columna"""
    print(f"--- {nombre}: {len(df)} filas, {df['id'].duplicated().sum()} ids repetidos")
    print((df.isna() | df.isin(VALORES_NULOS)).sum().to_string())


def limpiar_texto(df, columnas):
    """Saca espacios sobrantes y convierte textos vacios o None en nulos reales"""
    df = df.copy()
    for col in columnas:
        texto = df[col].astype("string").str.strip()
        texto = texto.str.replace(r"\s+", " ", regex=True)
        df[col] = texto.mask(texto.isin(VALORES_NULOS))
    return df  # perfilar(leer_delta(RUTA_OBRAS), "obras (crudo)") # cuantos vacios tiene cada fila.


def convertir_tipos(df):
    """Pasa de texto a su tipo real: entero, fecha con zona horaria y fecha"""
    df = df.copy()
    df["id"] = pd.to_numeric(df["id"], errors="coerce").astype("Int64") #el coerce es para que deje vacio los datos queden
    df["updated_at"] = pd.to_datetime(df["updated_at"], utc=True, errors="coerce")
    df["fecha"] = pd.to_datetime(df["fecha"], errors="coerce").dt.date

def quitar_duplicados(df):
    """elimina filas sin id y deja una sola fila por obra: su version mas reciente"""
    df = df.dropna(subset=["id"]).drop_duplicates()
    df = df.sort_values("updated_at", ascending=False)
    df = df.drop_duplicates(subset="id", keep="first")
    return df.reset_index(drop=True)

def tratar_nulos(df):
    """Reemplaza nulos por un valor explicito (date_display queda nulo)"""
    return df.fillna(VALORES_POR_DEFECTO)

def preparar_tipos(tipos):
    """ Limpia el catalogo de tipos de obra para poder cruzarlo con las obras"""
    tipos = limpiar_texto(tipos, tipos.columns)
    tipos = ["id"] = pd.to_numeric(tipos["id"], errors="coerce").astype("Int64")
    tipos = ["aat_id"] = pd.to_numeric(tipos["id"], errors="coerce").astype("Int64")
    tipos = tipos.dropna(subset=["title"]).drop_duplicates(subset="title")
    tipos = tipos.dropna(subset=["title"]).drop_duplicates(subset="title")
    return tipos.rename(columns={"id": "tipo_id", "title": "tipo_obra"})

def enriquecer(obras, tipos):
    """crea columnas nuevas y cruza las obras con el catalogo de tipos"""
    obras = obras.copy()
    anio = obras["fecha_texto"].str.extract(r"()")

print("todo joya")  # usado para chequear mientras trabajaba de que estaba todo ok
