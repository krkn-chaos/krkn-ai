import os
import joblib
import pandas as pd
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from krkn_ai.utils.logger import get_logger
from krkn_ai.utils.prometheus import KrknPrometheus

logger = get_logger(__name__)

class ScenarioRecommender:
    def __init__(self, prom_client: KrknPrometheus, model_path: str = None):
        self.prom_client = prom_client
        self.model_path = model_path
        self.model = None
        self.feature_names = ["cpu_usage", "memory_usage", "network_io"]
        
        if model_path and os.path.exists(model_path):
            self.load_model(model_path)

    def collect_telemetry(self, duration_minutes: int = 15) -> pd.DataFrame:
        """
        Collects telemetry data from Prometheus for the last N minutes.
        Returns a DataFrame with aggregated metrics.
        """
        logger.info("Collecting telemetry data for recommendation...")
        
        # Define queries for basic cluster health/state
        queries = {
            "cpu_usage": 'avg(cluster:node:cpu:ratio)',
            "memory_usage": 'avg(cluster:node:memory:utilization:ratio)',
            # Basic network I/O sum across cluster
            "network_io": 'sum(rate(container_network_receive_bytes_total[5m]))'
        }
        
        data = {}
        
        # We'll just take the current values for now as a snapshot
        # In a real system you might want time-series features
        for name, query in queries.items():
            try:
                # We use process_query to get instant vector
                result = self.prom_client.process_query(query)
                if result and len(result) > 0 and 'value' in result[0]:
                    # result[0]['value'] is [timestamp, "value"]
                    val = float(result[0]['value'][1])
                    data[name] = val
                else:
                    logger.warning(f"No data found for {name}, defaulting to 0")
                    data[name] = 0.0
            except Exception as e:
                logger.error(f"Failed to query {name}: {e}")
                data[name] = 0.0
                
        return pd.DataFrame([data])

    def train(self, X: pd.DataFrame, y: list, save_path: str = None):
        """
        Trains the Random Forest model.
        """
        logger.info("Training recommendation model...")
        self.model = RandomForestClassifier(n_estimators=100, random_state=42)
        self.model.fit(X[self.feature_names], y)
        
        if save_path:
            self.save_model(save_path)
            
    def recommend(self, telemetry_data: pd.DataFrame) -> str:
        """
        Returns a recommended chaos scenario based on telemetry.
        """
        if not self.model:
            raise Exception("Model not loaded or trained.")
            
        prediction = self.model.predict(telemetry_data[self.feature_names])
        return prediction[0]

    def save_model(self, path: str):
        logger.info(f"Saving model to {path}")
        joblib.dump(self.model, path)
        self.model_path = path

    def load_model(self, path: str):
        logger.info(f"Loading model from {path}")
        try:
            self.model = joblib.load(path)
        except Exception as e:
            logger.error(f"Failed to load model: {e}")
            raise
