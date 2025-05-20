import os
import pandas as pd
from typing import Dict, Union


def read_csv(file_path: str) -> pd.DataFrame:
    """Reads a CSV file into a pandas DataFrame.

    Args:
        file_path(str): Path to the CSV file.

    Returns:
        pd.DataFrame: DataFrame containing the CSV data.

    Raises:
        ValueError: Raised if the specified file does not exist.
    """
    if os.path.exists(file_path):
        return pd.read_csv(file_path)
    return ValueError(f"File {file_path} does not exist.")


def read_excel(file_path: str) -> Union[Dict[str, pd.DataFrame], None]:
    """Reads an Excel file into a dictionary of pandas DataFrames.

    Args:
        file_path(str): Path to the Excel file.

    Returns:
        Union[Dict[str, pd.DataFrame], None]: A dictionary where keys are sheet names and values are pandas DataFrames; returns None if the file does not exist.

    Raises:
        ValueError: Raised if the specified file does not exist.
    """
    if os.path.exists(file_path):
        return pd.read_excel(file_path, sheet_name=None)
    else:
        raise ValueError(f"File '{file_path}' does not exist.")