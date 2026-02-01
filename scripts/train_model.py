
import os
import sys
import pandas as pd
import numpy as np

# Add parent directory to path to allow importing krkn_ai
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from krkn_ai.recommendation import ScenarioRecommender
from krkn_ai.utils.logger import init_logger, get_logger

init_logger(None, True)
logger = get_logger("train_model")

def generate_synthetic_data(n_samples=1000):
    """
    Generates synthetic telemetry data with labeled chaos scenarios.
    
    Logic:
    - High CPU, Low Memory -> cpu-hog
    - Low CPU, High Memory -> memory-hog
    - High Network -> network-chaos
    - Balanced/Normal -> random/pod-delete (as a generic fallback)
    """
    data = []
    labels = []
    
    for _ in range(n_samples):
        # Generate random base metrics
        cpu = np.random.uniform(0, 1)        # 0 to 100% normalized
        memory = np.random.uniform(0, 1)     # 0 to 100% normalized
        network = np.random.uniform(0, 1000) # MB/s roughly
        
        # Rule-based labeling for "ground truth"
        if cpu > 0.8 and memory < 0.5:
            label = "cpu-hog"
        elif memory > 0.8 and cpu < 0.5:
            label = "memory-hog"
        elif network > 800:
            label = "network-chaos"
        else:
            # If nothing stands out, maybe suggest checking general resilience
            label = "pod-delete"
            
        data.append({
            "cpu_usage": cpu, 
            "memory_usage": memory, 
            "network_io": network
        })
        labels.append(label)
        
    return pd.DataFrame(data), labels

def main():
    logger.info("Generating synthetic data...")
    X, y = generate_synthetic_data()
    
    target_path = "krkn_model.pkl"
    
    # Initialize recommender (mocking prom client as None for training)
    recommender = ScenarioRecommender(prom_client=None)
    
    logger.info(f"Training model on {len(X)} samples...")
    recommender.train(X, y, save_path=target_path)
    
    logger.info(f"Model saved to {target_path}")
    
    # Test a prediction
    test_sample = pd.DataFrame([{
        "cpu_usage": 0.95, 
        "memory_usage": 0.2, 
        "network_io": 100
    }])
    prediction = recommender.recommend(test_sample)
    logger.info(f"Test Prediction for High CPU: {prediction} (Expected: cpu-hog)")

if __name__ == "__main__":
    main()
