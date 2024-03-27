import logging
import sys
import time

import yaml
from yaspin import yaspin
from yaspin.spinners import Spinners


def main():
    config = {}
    ai_chroma_db_path = ""
    ai_llm_endpoint = ""
    telemetry_api_endpoint = ""
    telemetry_username = ""
    telemetry_password = ""

    try:
        with open("config/config.yaml", "r") as stream:
            config = yaml.safe_load(stream)
    except Exception as e:
        logging.error(f"failed to load config file: {e}")
        sys.exit(1)

    # ai_chroma_db_path = config["ai"]["chroma_db_path"]
    # ai_llm_endpoint = config["ai"]["llm_enpoint"]
    # telemetry_api_endpoint = config["telemetry"]["api_endpoint"]
    with yaspin(Spinners.noise, text="Noise spinner") as sp:
        time.sleep(2)
        sp.text = "Arc spinner"  # text along with spinner
        sp.color = "green"  # spinner color
        sp.side = "right"  # put spinner to the right
        sp.reversal = True  # reverse spin direction

        time.sleep(2)


if __name__ == "__main__":
    main()
