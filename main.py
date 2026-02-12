from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import pandas as pd
import yfinance as yf
import io
import asyncio

app = FastAPI()

# Configuración de CORS para Lovable
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

async def analizar_ticker_async(ticker, spy_return_3m):
    """Procesamiento individual de cada acción"""
    try:
        loop = asyncio.get_event_loop()
        stock = yf.Ticker(ticker)
        # Obtenemos datos históricos
        hist = await loop.run_in_executor(None, lambda: stock.history(period="1y"))
        
        if len(hist) < 150: return None

        precio = hist['Close'].iloc[-1]
        sma_200 = hist['Close'].rolling(200).mean().iloc[-1]
        sma_150 = hist['Close'].rolling(150).mean().iloc[-1]
        
        # Filtro de tendencia Fase 2
        if (precio > sma_150 > sma_200):
            precio_3m = hist['Close'].iloc[-60]
            rs_rating = ((precio - precio_3m) / precio_3m * 100) - spy_return_3m
            vol_rel = hist['Volume'].iloc[-1] / hist['Volume'].rolling(50).mean().iloc[-1]

            return {
                "Symbol": ticker,
                "Precio": round(precio, 2),
                "RS_Rating": round(rs_rating, 2),
                "Vol_Relativo": round(vol_rel, 2),
                "Estado": "💎 ROTURA" if precio > hist['High'].iloc[-21:-1].max() else "✅ Calidad"
            }
    except Exception:
        return None

@app.get("/")
async def health_check():
    return {"status": "Sniper Elite API is Live"}

@app.post("/scan")
async def scan(
    file: UploadFile = File(...),
    min_price: float = Form(15.0),
    min_vol: int = Form(200000)
):
    try:
        # Lectura del archivo
        content = await file.read()
        df = pd.read_csv(io.BytesIO(content))
        
        # Limpiar espacios en los nombres de las columnas
        df.columns = [c.strip() for c in df.columns]

        # Buscador de columnas inteligente (evita fallos por nombres distintos)
        col_ticker = next((c for c in df.columns if c.lower() in ['symbol', 'ticker']), None)
        col_precio = next((c for c in df.columns if c.lower() in ['last sale', 'price', 'last']), None)
        col_vol = next((c for c in df.columns if c.lower() in ['volume', 'vol']), None)

        if not col_ticker or not col_precio:
            return {"error": f"Formato CSV inválido. Columnas detectadas: {list(df.columns)}"}

        # Corrección del SyntaxWarning: usamos r'' para el regex de limpieza de moneda
        if df[col_precio].dtype == object:
            df[col_precio] = df[col_precio].astype(str).str.replace(r'[\$,]', '', regex=True).astype(float)

        # Filtrado inicial por precio y volumen
        df_filtrado = df[(df[col_precio] >= min_price) & (df[col_vol] >= min_vol)]
        candidatos = df_filtrado[col_ticker].tolist()[:35]

        # Referencia del mercado (SPY)
        spy = yf.Ticker("SPY").history(period="6mo")
        spy_ret = ((spy['Close'].iloc[-1] - spy['Close'].iloc[-60]) / spy['Close'].iloc[-60]) * 100

        # Procesamiento paralelo
        tasks = [analizar_ticker_async(t, spy_ret) for t in candidatos]
        resultados = await asyncio.gather(*tasks)

        return [r for r in resultados if r is not None]

    except Exception as e:
        # Retornamos el error como JSON para que Lovable pueda mostrarlo
        return {"error": f"Error interno: {str(e)}"}