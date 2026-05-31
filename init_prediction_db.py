#!/usr/bin/env python3
from repositories.prediction_repo import PredictionRepository

if __name__ == "__main__":
    PredictionRepository().init_tables()
    print("Prediction tables initialized.")
