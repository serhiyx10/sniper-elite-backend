from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import pandas as pd
import yfinance as yf
import io
import asyncio
import time

app = FastAPI(title="Sniper Elite API")

# --- CONFIGURACIÓN DE SEGURIDAD (CORS) ---
# Esto permite que tu frontend en Lovable haga peticiones a este servidor
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

async def analizar_ticker_async(ticker, spy_return_3m):
    """Procesa un solo ticker de forma asíncrona para maximizar velocidad"""
    try:
        # Usamos hilos para yfinance ya que no es nativamente asíncrona
        loop = asyncio.get_event_loop()
        stock = yf.Ticker(ticker)
        hist = await loop.run_in_executor(None, lambda: stock.history(period="1y"))
        
        if len(hist) < 200:
            return None

        # --- CÁLCULOS TÉCNICOS ---
        precio = hist['Close'].iloc[-1]
        sma_200 = hist['Close'].rolling(200).mean().iloc[-1]
        sma_150 = hist['Close'].rolling(150).mean().iloc[-1]
        vol_hoy = hist['Volume'].iloc[-1]
        vol_medio = hist['Volume'].rolling(50).mean().iloc[-1]
        max_20_dias = hist['High'].iloc[-21:-1].max()
        min_20_dias = hist['Low'].iloc[-21:-1].min()
        
        # Filtros de Fase 2 (Weinstein)
        tecnico_fase2 = (precio > sma_150 > sma_200)
        cerca_maximos = precio >= (0.80 * hist['High'].max())

        if tecnico_fase2 and cerca_maximos:
            # Fuerza Relativa (RS)
            precio_3m_atras = hist['Close'].iloc[-60]
            stock_return_3m = ((precio - precio_3m_atras) / precio_3m_atras) * 100
            rs_rating = stock_return_3m - spy_return_3m
            
            vol_rel = round(vol_hoy / vol_medio, 2) if vol_medio > 0 else 0
            es_rotura = (vol_rel > 1.5) and (precio > max_20_dias)

            return {
                "Symbol": ticker,
                "Precio": round(precio, 2),
                "Stop_Loss": round(min_20_dias * 0.98, 2),
                "Vol_Relativo": vol_rel,
                "RS_Rating": round(rs_rating, 2),
                "Estado": "💎 ROTURA PURA" if es_rotura else "✅ Calidad",
                "Link": f"https://finviz.com/quote.ashx?t={ticker}"
            }
    except Exception:
        return None
    return None

@app.get("/")
def home():
    return {"status": "Sniper Elite Terminal API is Running"}

@app.post("/scan")
async def scan(
    file: UploadFile = File(...),
    min_price: float = Form(15.0),
    min_vol: int = Form(200000)
):
    try:
        # 1. Leer el archivo CSV subido
        content = await file.read()
        df = pd.read_csv(io.BytesIO(content))
        df.columns = [c.strip() for c in df.columns]

        # 2. Limpieza de datos (Precio)
        if df['Last Sale'].dtype == object:
            df['Last Sale'] = df['Last Sale'].replace({'\$': '', ',': ''}, regex=True).astype(float)

        # 3. Filtro rápido inicial
        candidatos = df[
            (df['Last Sale'] >= min_price) & 
            (df['Volume'] >= min_vol)
        ]['Symbol'].tolist()[:40] # Limitamos a 40 para no saturar la API gratuita

        # 4. Obtener rendimiento del SPY para el RS Rating
        spy = yf.Ticker("SPY").history(period="6mo")
        spy_ret = ((spy['Close'].iloc[-1] - spy['Close'].iloc[-60]) / spy['Close'].iloc[-60]) * 100

        # 5. Ejecutar análisis en paralelo
        tasks = [analizar_ticker_async(t, spy_ret) for t in candidatos]
        resultados = await asyncio.gather(*tasks)

        # 6. Filtrar nulos y devolver
        final_data = [r for r in resultados if r is not None]
        return final_data

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))