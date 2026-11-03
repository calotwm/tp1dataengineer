import requests

url = "https://api.artic.edu/api/v1/artwork-types"
headers = {"AIC-User-Agent": "TP1-UTN (camiloseifar@gmail.com)"}

respuesta = requests.get(url, params={"limit": 10}, headers=headers, timeout=1)

print(respuesta.status_code)
print(respuesta.text[:300]) 