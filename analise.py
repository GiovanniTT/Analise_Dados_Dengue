import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.engine import URL

url = URL.create(
    drivername="mysql+pymysql",
    username="giovanni",
    password="Senha@123",  # aqui pode usar normal
    host="localhost",
    port=3306,
    database="dengue_db"
)

engine = create_engine(url)

df = pd.read_sql(
    """
    SELECT *
    FROM dengue_dados
    ORDER BY ano, mes
    LIMIT 5
    """,
    engine
)

print(df)