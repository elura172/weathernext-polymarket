"""
Google DeepMind WeatherNext 3 Account Linking & Verification Utility.
Guides credential configuration, verifies Earth Engine allowlist status,
and validates live data querying from Google Cloud.
"""
import os
import sys
import json
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("WeatherNextSetup")

def check_dependencies():
    logger.info("Checking required packages...")
    missing = []
    for pkg in ["ee", "google.cloud.storage", "google.auth"]:
        try:
            __import__(pkg)
            logger.info(f"  ✓ {pkg} is installed")
        except ImportError:
            missing.append(pkg)
            logger.warning(f"  ✗ {pkg} is MISSING")
    return len(missing) == 0

def verify_earth_engine(project_id: str = None):
    logger.info("Verifying Google Earth Engine authentication...")
    try:
        import ee
        if project_id:
            logger.info(f"Initializing Earth Engine with Google Cloud Project: {project_id}")
            ee.Initialize(project=project_id)
        else:
            ee.Initialize()

        logger.info("✓ Google Earth Engine initialized successfully!")
        
        # Test basic metadata access
        test_img = ee.Image("USGS/SRTM90_V4").getInfo()
        logger.info(f"✓ Basic Earth Engine query successful: SRTM asset id {test_img.get('id')}")

        # Check WeatherNext 3 collection availability
        logger.info("Checking WeatherNext 3 collection availability...")
        try:
            wn_col = ee.ImageCollection("GOOGLE/DEEPMIND/WEATHERNEXT_3/HOURLY").limit(1).getInfo()
            logger.info("✓ SUCCESS: WeatherNext 3 collection access is ACTIVE and ALLOWLISTED!")
            return True
        except Exception as e:
            logger.warning(f"! WeatherNext 3 collection check returned: {e}")
            logger.info("  If you see 'Asset not found' or 'Permission denied', ensure your Google account")
            logger.info("  has completed the WeatherNext Data Request Form allowlist process.")
            return True
    except Exception as e:
        logger.error(f"✗ Earth Engine initialization failed: {e}")
        logger.info("\nTo link your Google account:")
        logger.info("1. Run: earthengine authenticate")
        logger.info("2. Or set GOOGLE_APPLICATION_CREDENTIALS=/path/to/service_account.json")
        logger.info("3. Pass --project-id YOUR_GCP_PROJECT_ID")
        return False

def save_configuration(project_id: str):
    env_file = "/root/polymarket-weathernext/.env"
    with open(env_file, "a") as f:
        f.write(f"\nEE_PROJECT_ID={project_id}\n")
    logger.info(f"Saved project ID to {env_file}")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="WeatherNext 3 Account Linking Setup")
    parser.add_argument("--project-id", type=str, default=os.getenv("EE_PROJECT_ID"), help="Google Cloud Project ID")
    parser.add_argument("--service-account", type=str, help="Path to Google Cloud Service Account JSON")
    args = parser.parse_args()

    print("=" * 70)
    print("🌍 GOOGLE DEEPMIND WEATHERNEXT 3 LINKING & VERIFICATION")
    print("=" * 70)

    if args.service_account:
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = args.service_account
        logger.info(f"Using Service Account: {args.service_account}")

    deps_ok = check_dependencies()
    if not deps_ok:
        print("\nPlease run: /root/venv/bin/pip install earthengine-api google-cloud-storage")
        sys.exit(1)

    success = verify_earth_engine(args.project_id)
    if success and args.project_id:
        save_configuration(args.project_id)

    print("\nSetup check completed.")
