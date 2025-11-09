# Run this on your host: python test/check_syntax.py
import sys
sys.path.insert(0, '.')

try:
    from neurokit.health import HealthEndpoint
    print("✓ HealthEndpoint imported successfully")
    health = HealthEndpoint(uid="test")
    print("✓ Instantiated OK")
except ImportError as e:
    print(f"✗ Import error: {e}")
except Exception as e:
    print(f"✗ Other error: {e}")
