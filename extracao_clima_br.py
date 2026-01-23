import pandas as pd
import glob
import os
import re
import json
from typing import List, Dict, Any, Optional
from io import StringIO
from datetime import datetime

import psycopg2
from psycopg2.extras import execute_batch, Json, RealDictCursor


class DengueCSVProcessor:

    def __init__(self, pg_config: Optional[Dict] = None):

        self.meses_map = {
            'Janeiro': 'Janeiro',
            'Fevereiro': 'Fevereiro',
            'Marco': 'Marco',
            'Abril': 'Abril',
            'Maio': 'Maio',
            'Junho': 'Junho',
            'Julho': 'Julho',
            'Agosto': 'Agosto',
            'Setembro': 'Setembro',
            'Outubro': 'Outubro',
            'Novembro': 'Novembro',
            'Dezembro': 'Dezembro'
        }

        self.estados_map = {
            '11': 'RO', '12': 'AC', '13': 'AM', '14': 'RR', '15': 'PA', '16': 'AP',
            '17': 'TO', '21': 'MA', '22': 'PI', '23': 'CE', '24': 'RN', '25': 'PB',
            '26': 'PE', '27': 'AL', '28': 'SE', '29': 'BA', '31': 'MG', '32': 'ES',
            '33': 'RJ', '35': 'SP', '41': 'PR', '42': 'SC', '43': 'RS', '50': 'MS',
            '51': 'MT', '52': 'GO', '53': 'DF'
        }

        self.colunas_ignoradas = {
            'IG', 'IGNORADO', 'IGNORADO/EXTERIOR', 'EXTERIOR',
            'TOTAL', '00', '00 IGNORADO'
        }

        self.dados_consolidados = {}

        self.pg_config = pg_config
        self.connection = None

    # ==========================================================
    # CONEXÃO POSTGRES
    # ==========================================================
    def create_postgres_connection(self) -> bool:
        try:
            self.connection = psycopg2.connect(**self.pg_config)
            print("Conectado ao PostgreSQL")
            return True
        except Exception as e:
            print(f"Erro ao conectar no PostgreSQL: {e}")
            return False

    def close_postgres_connection(self):
        if self.connection:
            self.connection.close()
            print("🔒 Conexão PostgreSQL fechada")

    # ==========================================================
    # CRIAÇÃO DAS TABELAS
    # ==========================================================
    def create_tables(self):

        ddl = """
        CREATE TABLE IF NOT EXISTS dengue_dados (
            id SERIAL PRIMARY KEY,
            ano INT NOT NULL,
            mes VARCHAR(20) NOT NULL,
            estado VARCHAR(2) NOT NULL,
            casos INT DEFAULT 0,
            mortes INT DEFAULT 0,
            temperatura NUMERIC(5,2) DEFAULT 0,
            precipitacao NUMERIC(8,2) DEFAULT 0,
            data_criacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            data_atualizacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (ano, mes, estado)
        );

        CREATE TABLE IF NOT EXISTS processamento_log (
            id SERIAL PRIMARY KEY,
            arquivo VARCHAR(255),
            tipo_dados VARCHAR(20),
            ano INT,
            registros_processados INT,
            status VARCHAR(20),
            mensagem TEXT,
            data_processamento TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS estatisticas (
            id SERIAL PRIMARY KEY,
            total_registros INT,
            anos_processados JSONB,
            estados_processados JSONB,
            total_casos INT,
            total_mortes INT,
            data_atualizacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """

        with self.connection.cursor() as cursor:
            cursor.execute(ddl)
            self.connection.commit()

        print("Tabelas criadas/verificadas")

    # ==========================================================
    # INSERT / UPSERT
    # ==========================================================
    def insert_data_to_postgres(self):

        insert_sql = """
        INSERT INTO dengue_dados
        (ano, mes, estado, casos, mortes, temperatura, precipitacao)
        VALUES (%(Ano)s, %(Mes)s, %(Estado)s, %(Casos)s, %(Mortes)s, %(Temperatura)s, %(Precipitacao)s)
        ON CONFLICT (ano, mes, estado)
        DO UPDATE SET
            casos = EXCLUDED.casos,
            mortes = EXCLUDED.mortes,
            temperatura = EXCLUDED.temperatura,
            precipitacao = EXCLUDED.precipitacao,
            data_atualizacao = CURRENT_TIMESTAMP
        """

        dados = list(self.dados_consolidados.values())

        with self.connection.cursor() as cursor:
            execute_batch(cursor, insert_sql, dados, page_size=1000)
            self.connection.commit()

        print(f"{len(dados)} registros inseridos/atualizados")

    def update_statistics(self):

        with self.connection.cursor(cursor_factory=RealDictCursor) as cursor:

            cursor.execute("""
                SELECT COUNT(*) total_registros,
                       SUM(casos) total_casos,
                       SUM(mortes) total_mortes
                FROM dengue_dados
            """)
            stats = cursor.fetchone()

            cursor.execute("SELECT DISTINCT ano FROM dengue_dados ORDER BY ano")
            anos = [r['ano'] for r in cursor.fetchall()]

            cursor.execute("SELECT DISTINCT estado FROM dengue_dados ORDER BY estado")
            estados = [r['estado'] for r in cursor.fetchall()]

            cursor.execute("DELETE FROM estatisticas")

            cursor.execute("""
                INSERT INTO estatisticas
                (total_registros, anos_processados, estados_processados, total_casos, total_mortes)
                VALUES (%s, %s, %s, %s, %s)
            """, (
                stats['total_registros'],
                Json(anos),
                Json(estados),
                stats['total_casos'] or 0,
                stats['total_mortes'] or 0
            ))

            self.connection.commit()

        print("Estatísticas atualizadas")

    def process_multiple_csvs(self, csv_dir):

        arquivos = glob.glob(os.path.join(csv_dir, "*.csv"))

        for arquivo in arquivos:
            ano = int(re.search(r'\d{4}', arquivo).group())
            tipo = 'mortes' if arquivo.lower().endswith('d.csv') else 'casos'

            df = pd.read_csv(arquivo, sep=';', encoding='latin1')

            for _, row in df.iterrows():
                mes = row.iloc[0]
                if mes not in self.meses_map:
                    continue

                for col in df.columns[1:]:
                    if col in self.colunas_ignoradas:
                        continue

                    uf = self.estados_map.get(col[:2])
                    if not uf:
                        continue

                    valor = int(row[col]) if pd.notna(row[col]) else 0
                    key = (ano, mes, uf)

                    if key not in self.dados_consolidados:
                        self.dados_consolidados[key] = {
                            'Ano': ano,
                            'Mes': mes,
                            'Estado': uf,
                            'Casos': 0,
                            'Mortes': 0,
                            'Temperatura': 0.0,
                            'Precipitacao': 0.0
                        }

                    if tipo == 'casos':
                        self.dados_consolidados[key]['Casos'] = valor
                    else:
                        self.dados_consolidados[key]['Mortes'] = valor

        print(f"CSVs processados: {len(self.dados_consolidados)} registros consolidados")

    def execute_pipeline(self, csv_dir):

        self.create_postgres_connection()
        self.create_tables()
        self.process_multiple_csvs(csv_dir)
        self.insert_data_to_postgres()
        self.update_statistics()
        self.close_postgres_connection()

if __name__ == "__main__":

    pg_config = {
        "host": "localhost",
        "user": "postgres",
        "password": "SUA_SENHA",
        "dbname": "dengue_db",
        "port": 5432
    }

    processor = DengueCSVProcessor(pg_config)

    dados_dir = "./dados_casos_mortes"

    if os.path.exists(dados_dir):
        processor.execute_pipeline(dados_dir)
    else:
        print("Diretório de dados não encontrado")
