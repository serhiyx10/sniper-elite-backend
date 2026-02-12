from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import pandas as pd
import yfinance as yf
import io
import asyncio

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

async def analizar_ticker_async(ticker, spy_return_3m):
    try:
        loop = asyncio.get_event_loop()
        stock = yf.Ticker(ticker)
        # Periodo corto para acelerar la respuesta inicial
        hist = await loop.run_in_executor(None, lambda: stock.history(period="1y"))
        
        if len(hist) < 150: return None

        precio = hist['Close'].iloc[-1]
        sma_200 = hist['Close'].rolling(200).mean().iloc[-1]
        sma_150 = hist['Close'].rolling(150).mean().iloc[-1]
        
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
    except:
        return None

@app.get("/")
async def root():
    return {"message": "Sniper Elite API is active"}

@app.post("/scan")
async def scan(
    file: UploadFile = File(...),
    min_price: float = Form(15.0),
    min_vol: int = Form(200000)
):
    try:
        content = await file.read()
        df = pd.read_csv(io.BytesIO(content))
        
        # Limpieza agresiva de columnas
        df.columns = [c.strip() for c in df.columns]

        # Buscador inteligente de columnas (soporta 'Symbol', 'Ticker', 'Last Sale', 'Price')
        col_ticker = next((c for c in df.columns if c.lower() in ['symbol', 'ticker']), None)
        col_precio = next((c for c in df.columns if c.lower() in ['last sale', 'price', 'last']), None)
        col_vol = next((c for c in df.columns if c.lower() in ['volume', 'vol']), None)

        if not col_ticker or not col_precio:
            raise ValueError(f"No se detectaron columnas de Ticker o Precio. Columnas: {list(df.columns)}")

        # Corrección del error de escape detectado en los logs
        if df[col_precio].dtype == object:
            df[col_precio] = df[col_precio].astype(str).str.replace(r'[\$,]', '', regex=True).astype(float)

        # Filtrado inicial
        df_filtrado = df[(df[col_precio] >= min_price) & (df[col_vol] >= min_vol)]
        candidatos = df_filtrado[col_ticker].tolist()[:30] # Bajamos a 30 para evitar timeouts

        spy = yf.Ticker("SPY").history(period="6mo")
        spy_ret = ((spy['Close'].iloc[-1] - spy['Close'].iloc[-60]) / spy['Close'].iloc[-60]) * 100

        tasks = [analizar_ticker_async(t, spy_ret) for t in candidatos]
        resultados = await asyncio.gather(*tasks)

        return [r for r in resultados if r is not None]

    except Exception as e:
        # Esto enviará el error real a Lovable para que sepas qué falló
        return {"error": str(e)}