import pandas as pd
import glob
import os
import re
import json
from typing import List, Dict, Any, Optional
from io import StringIO
from datetime import datetime
from typing import Dict, List, TypedDict, Union, Optional

import pandas
from numpy import float64
from pandas import Series

processed_files = 0
written_outputs = 0

write_lock = threading.Lock()
progress_lock = threading.Lock()

STATE_DICT = {
    "AC": "Acre",
    "AP": "Amapá",
    "AM": "Amazonas",
    "PA": "Pará",
    "RO": "Rondônia",
    "RR": "Roraima",
    "TO": "Tocantins",
    "AL": "Alagoas",
    "BA": "Bahia",
    "CE": "Ceará",
    "MA": "Maranhão",
    "PB": "Paraíba",
    "PE": "Pernambuco",
    "PI": "Piauí",
    "RN": "Rio Grande do Norte",
    "SE": "Sergipe",
    "DF": "Distrito Federal",
    "GO": "Goiás",
    "MT": "Mato Grosso",
    "MS": "Mato Grosso do Sul",
    "ES": "Espírito Santo",
    "MG": "Minas Gerais",
    "RJ": "Rio de Janeiro",
    "SP": "São Paulo",
    "PR": "Paraná",
    "RS": "Rio Grande do Sul",
    "SC": "Santa Catarina"
}

MONTH_DICT = {
    1: "Janeiro",
    2: "Fevereiro",
    3: "Março",
    4: "Abril",
    5: "Maio",
    6: "Junho",
    7: "Julho",
    8: "Agosto",
    9: "Setembro",
    10: "Outubro",
    11: "Novembro",
    12: "Dezembro",
}


class YearData(TypedDict):
    """
    A TypedDict representing yearly data.

    Attributes:
        precipitation (float): The total precipitation for the year, measured in millimeters.
        temperature_avg (float): The average temperature for the year, measured in Celsius.
    """

    precipitation: float64
    temperature_avg: float64


class PreProcessedData(TypedDict):
    """
    PreProcessedData is a TypedDict that represents the structure of pre-processed data.

    Attributes:
        uf (str): The state abbreviation (e.g., 'SP' for São Paulo).
        day_and_month (Series): A pandas Series containing day and month information.
        precipitation (Series): A pandas Series containing precipitation data.
        temp_max (Series): A pandas Series containing maximum temperature data.
        temp_min (Series): A pandas Series containing minimum temperature data.
    """

    uf: str
    day_and_month: Series
    precipitation: Series
    temp_max: Series
    temp_min: Series


class OutputData(TypedDict):
    """
    OutputData is a TypedDict that represents the structure of output data.

    Attributes:
        uf (str): The abbreviation of the state (Unidade Federativa) in Brazil.
        year (int): The year associated with the data.
        day_and_month (str): The day and month in the format "DD/MM".
        data (YearData): The data associated with the specified year.
    """
    uf: str
    year: int
    day_and_month: Union[str, int]
    data: YearData


def convert_int_str_to_float(col: Union[str, int]) -> float64:
    """
    Converts an integer or a string representing a number into a float64 value.
    """
    
    if isinstance(col, int):
        if col >= 0:
            return float64(col)
        return float64(0.0)
    elif isinstance(col, str):
        col = col.strip()
        if col == "" or col == "-9999":
            return float64(0.0)
        try:
            find_idx = col.find(',')
            if find_idx == 0:
                col_tr = float64(col.replace(",", "0."))
            else:
                col_tr = float64(col.replace(',', '.'))
            if col_tr >= 0:
                return col_tr
        except (ValueError, TypeError):
            return float64(0.0)
    return float64(0.0)


def convert_temperature_str_to_float(col: Union[str, int]) -> float64:
    """
    Converts temperature data (string or int) to float64, handling negative values.
    """
    
    if isinstance(col, int):
        return float64(col)
    elif isinstance(col, str):
        col = col.strip()
        if col == "" or col == "-9999":
            return float64(0.0)
        try:
            find_idx = col.find(',')
            if find_idx == 0:
                col_tr = float64(col.replace(",", "0."))
            else:
                col_tr = float64(col.replace(',', '.'))
            return col_tr  # Allow negative temperatures
        except (ValueError, TypeError):
            return float64(0.0)
    return float64(0.0)


def convert_str_to_day_and_month(line: str) -> str:
    """
    Converts a date string to day/month format with robust error handling.
    """
    if not line or pandas.isna(line):
        return "1/1"  # Default fallback
    
    try:
        line = str(line).strip()
        
        # Handle different date formats
        if '/' in line:
            parts = line.split('/')
            if len(parts) >= 3:
                if len(parts[0]) == 4:  # YYYY/MM/DD
                    year, month, day = parts[0], parts[1], parts[2]
                else:  # DD/MM/YYYY
                    day, month, year = parts[0], parts[1], parts[2]
                return f"{int(day)}/{int(month)}"
        elif '-' in line:
            # Handle ISO format YYYY-MM-DD
            date = datetime.fromisoformat(line.split()[0])  # Remove time if present
            return f"{date.day}/{date.month}"
        else:
            # Try to parse as timestamp or other formats
            try:
                date = pandas.to_datetime(line)
                return f"{date.day}/{date.month}"
            except:
                return "1/1"
                
    except (ValueError, IndexError, TypeError) as e:
        print(f"Erro ao converter data '{line}': {e}")
        return "1/1"  # Default fallback


def get_files() -> List[str]:
    """
    Retrieves a list of all CSV files in the current directory and its subdirectories.
    """
    files = glob("./**/*.csv", recursive=True)
    return files


def get_path_year(path: str) -> int:
    """
    Extracts year from path with error handling.
    """
    try:
        # Try different path separators
        path_split = path.replace('/', '\\').split("\\")
        for part in path_split:
            if part.isdigit() and len(part) == 4:
                year = int(part)
                if 1900 <= year <= 2100:  # Reasonable year range
                    return year
        
        # Fallback: try to find year in filename
        filename = Path(path).stem
        for part in filename.split('_'):
            if part.isdigit() and len(part) == 4:
                year = int(part)
                if 1900 <= year <= 2100:
                    return year
        
        return 2000  # Default fallback
    except (ValueError, IndexError):
        return 2000


def show_progress(stage: str, current: int, length: int) -> None:
    """
    Displays a progress update in the console.
    """
    try:
        os.system("cls" if os.name == 'nt' else "clear")
        print(stage)
        print(f"{current}/{length}")
    except:
        pass  # Continue if screen clear fails


def read_csv(path: str) -> Optional[PreProcessedData]:
    """
    Reads a CSV file with robust error handling, now including temperature data.
    """
    try:
        # ===============================
        # 1️⃣ LEITURA DE METADADOS (UF)
        # ===============================
        uf = None
        encodings_meta = ["ansi", "latin1", "cp1252", "utf-8"]

        for enc in encodings_meta:
            try:
                file_metadata = pandas.read_csv(
                    path,
                    encoding=enc,
                    sep=";",
                    nrows=8,
                    header=None
                )

                file_metadata[0] = (
                    file_metadata[0]
                    .astype(str)
                    .str.replace("\ufeff", "", regex=False)
                    .str.strip()
                )
                file_metadata[1] = file_metadata[1].astype(str).str.strip()

                metadata_dict = dict(zip(file_metadata[0], file_metadata[1]))

                for key in ("UF:", "UF"):
                    if key in metadata_dict:
                        candidate = metadata_dict[key].upper()
                        if candidate in STATE_DICT:
                            uf = candidate
                            break

                if uf:
                    break
            except:
                continue

        if uf is None:
            print(f"⚠️ UF não identificada → {path}")
            return None

        # ===============================
        # 2️⃣ LEITURA DOS DADOS
        # ===============================
        encodings = ["ansi", "utf-8", "latin1", "cp1252"]
        file_data = None
        
        for encoding in encodings:
            try:
                file_data = pandas.read_csv(
                    path,
                    encoding=encoding,
                    on_bad_lines="skip",
                    sep=";",
                    engine="python",
                    skiprows=8,
                    converters={
                        "PRECIPITAÇÃO TOTAL, HORÁRIO (mm)": convert_int_str_to_float,
                        "PRECIPITA  O TOTAL, HOR RIO (mm)": convert_int_str_to_float,
                        "TEMPERATURA M XIMA NA HORA ANT. (AUT) ( C)": convert_temperature_str_to_float,
                        "TEMPERATURA M NIMA NA HORA ANT. (AUT) ( C)": convert_temperature_str_to_float,
                        "TEMPERATURA MÁXIMA NA HORA ANT. (AUT) (°C)": convert_temperature_str_to_float,
                        "TEMPERATURA MÍNIMA NA HORA ANT. (AUT) (°C)": convert_temperature_str_to_float,
                        "DATA (YYYY-MM-DD)": convert_str_to_day_and_month,
                        "DATA": convert_str_to_day_and_month,
                        "Data": convert_str_to_day_and_month
                    },
                )
                break
            except:
                continue
        
        if file_data is None:
            print(f"Erro ao ler arquivo: {path}")
            return None

        # ===============================
        # 3️⃣ IDENTIFICAÇÃO DE COLUNAS
        # ===============================
        date_columns = ["DATA (YYYY-MM-DD)", "DATA", "Data", "data"]
        date = next((file_data[c] for c in date_columns if c in file_data.columns), None)

        if date is None:
            print(f"Coluna de data não encontrada em: {path}")
            return None

        precip_columns = [
            "PRECIPITAÇÃO TOTAL, HORÁRIO (mm)",
            "PRECIPITA  O TOTAL, HOR RIO (mm)",
            "PRECIPITACAO TOTAL, HORARIO (mm)",
            "PRECIPITAÇÃO TOTAL (mm)",
            "PRECIPITACAO TOTAL (mm)",
            "PRECIPITAÇÃO",
            "PRECIPITACAO"
        ]

        precipitation_data = next(
            (file_data[c] for c in precip_columns if c in file_data.columns), None
        )

        if precipitation_data is None:
            print(f"Coluna de precipitação não encontrada em: {path}")
            return None

        temp_max_columns = [
            "TEMPERATURA M XIMA NA HORA ANT. (AUT) ( C)",
            "TEMPERATURA MÁXIMA NA HORA ANT. (AUT) (°C)",
            "TEMPERATURA MAXIMA NA HORA ANT. (AUT) (C)",
            "TEMPERATURA MAX NA HORA ANT. (AUT)",
            "TEMP MAX"
        ]

        temp_min_columns = [
            "TEMPERATURA M NIMA NA HORA ANT. (AUT) ( C)",
            "TEMPERATURA MÍNIMA NA HORA ANT. (AUT) (°C)",
            "TEMPERATURA MINIMA NA HORA ANT. (AUT) (C)",
            "TEMPERATURA MIN NA HORA ANT. (AUT)",
            "TEMP MIN"
        ]

        temp_max_data = next(
            (file_data[c] for c in temp_max_columns if c in file_data.columns),
            pandas.Series(dtype=float64)
        )

        temp_min_data = next(
            (file_data[c] for c in temp_min_columns if c in file_data.columns),
            pandas.Series(dtype=float64)
        )

        return {
            "uf": uf,
            "day_and_month": date.dropna(),
            "precipitation": precipitation_data.dropna(),
            "temp_max": temp_max_data.dropna(),
            "temp_min": temp_min_data.dropna(),
        }

    except Exception as e:
        print(f"Erro ao processar arquivo {path}: {e}")
        return None

def process_file(file_path: str, pre_processed_data: Dict[int, Dict[str, List[PreProcessedData]]], total_files: int) -> None:
    """
    Processa um único arquivo CSV com tratamento de erros robusto.
    """
    global processed_files

    try:
        year = get_path_year(file_path)
        data = read_csv(file_path)
        
        if data is None:
            processed_files += 1
            return

        with progress_lock:
            if year not in pre_processed_data:
                pre_processed_data[year] = {}

            if data["uf"] not in pre_processed_data[year]:
                pre_processed_data[year][data["uf"]] = []
            
            pre_processed_data[year][data["uf"]].append(data)
        
        processed_files += 1
        show_progress("Lendo arquivos...", processed_files, total_files)
        
    except Exception as e:
        print(f"Erro ao processar arquivo {file_path}: {e}")
        processed_files += 1


def process_state_data(year: int, state_data: Dict[str, List[PreProcessedData]]) -> List[OutputData]:
    """
    Processes data for a specific year and state with error handling, now including temperature.
    """
    output_data: List[OutputData] = []

    try:
        for state, pre_data in state_data.items():
            if not pre_data:
                continue
                
            # Filter out None values and empty data
            valid_data = [data for data in pre_data if data is not None and 
                         data.get("day_and_month") is not None and 
                         data.get("precipitation") is not None]
            
            if not valid_data:
                continue

            try:
                # Combine data more safely
                dataframes = []
                for data in valid_data:
                    try:
                        # Calculate average temperature from max and min
                        temp_avg_series = pandas.Series(dtype=float64)
                        
                        if (len(data["temp_max"]) > 0 and len(data["temp_min"]) > 0 and
                            len(data["temp_max"]) == len(data["temp_min"])):
                            temp_avg_series = (data["temp_max"] + data["temp_min"]) / 2
                        
                        df = pandas.DataFrame({
                            "day_and_month": data["day_and_month"], 
                            "precipitation": data["precipitation"],
                            "temp_avg": temp_avg_series if len(temp_avg_series) > 0 else pandas.Series([0.0] * len(data["day_and_month"]), dtype=float64)
                        })
                        dataframes.append(df)
                    except Exception as e:
                        print(f"Erro ao criar DataFrame para {state}: {e}")
                        continue
                
                if not dataframes:
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
