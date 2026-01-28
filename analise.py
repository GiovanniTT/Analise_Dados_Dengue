import pandas as pd
import numpy as np

from sqlalchemy import create_engine
from sqlalchemy.engine import URL

url = URL.create(
    drivername="mysql+pymysql",
    username="*****",
    password="*****",
    host="localhost",
    port=3306,
    database="dengue_db"
)

engine = create_engine(url)

df = pd.read_sql(
    """
    SELECT *
    FROM dengue_dados
    ORDER BY estado, ano, mes
    """,
    engine
)

df['casos'] = pd.to_numeric(df['casos'], errors='coerce')

df['casos_movel_12'] = (
    df.groupby('estado')['casos']
      .transform(lambda x: x.rolling(12, min_periods=1).mean())
)

df.replace([np.inf, -np.inf], np.nan, inplace=True)

p50 = df['casos_movel_12'].quantile(0.50)
p75 = df['casos_movel_12'].quantile(0.75)
p90 = df['casos_movel_12'].quantile(0.90)

def classificar_risco(valor):
    if valor <= p50:
        return 'Baixo'
    elif valor <= p75:
        return 'Médio'
    elif valor <= p90:
        return 'Alto'
    else:
        return 'Epidêmico'

df['nivel_risco'] = df['casos_movel_12'].apply(classificar_risco)

print("\nAMOSTRA DOS DADOS ENRIQUECIDOS")
print(df.head(10))

model_df = df.dropna(subset=[
    'casos',
    'temperatura',
    'precipitacao',
    'casos_movel_12'
])

corr_df = (
    model_df
    .groupby('estado')[['casos', 'temperatura', 'precipitacao']]
    .corr()
    .reset_index()
)

df.to_sql(
    "dengue_dados_enriquecidos",
    engine,
    if_exists="replace",
    index=False
)

corr_df.to_sql(
    "correlacao_casos_clima_estado",
    engine,
    if_exists="replace",
    index=False
)

print("\nDados salvos com sucesso no banco!")