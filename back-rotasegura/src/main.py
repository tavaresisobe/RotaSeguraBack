from fastapi import FastAPI
from pydantic import BaseModel
from src.router import calculate_safe_route
import uvicorn

app = FastAPI()

class RouteRequest(BaseModel):
    origin_street: str
    destination_street: str
    max_crime_occurrences: int

@app.post("/calculate-route")
def get_safe_route(request: RouteRequest):
    """
    Recebe os dados de origem, destino e limite de crimes,
    chama a função de cálculo e retorna o resultado.
    """
    print(f"Recebida requisição para rota de '{request.origin_street}' para '{request.destination_street}' com limite de {request.max_crime_occurrences} ocorrências.")

    result = calculate_safe_route(
        origin_street=request.origin_street,
        destination_street=request.destination_street,
        max_crime_occurrences=request.max_crime_occurrences
    )

    return result

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
