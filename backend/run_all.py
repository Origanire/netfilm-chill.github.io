import subprocess
import os

def run_backend(script, env=None):
    return subprocess.Popen([
        'python', script
    ], env=env)

if __name__ == "__main__":
    base_dir = os.path.dirname(__file__)
    env_blindtest = os.environ.copy()
    env_blindtest["BLINDTEST_PORT"] = "5002"
    p1 = run_backend(os.path.join(base_dir, "app_akinator.py"))
    p2 = run_backend(os.path.join(base_dir, "app_blindtest.py"), env=env_blindtest)
    p3 = run_backend(os.path.join(base_dir, "app_moviegrid.py"))
    print("Akinator lancé sur le port 5001.")
    print("BlindTest lancé sur le port 5002.")
    print("MovieGrid lancé sur le port 5003.")
    p1.wait()
    p2.wait()
    p3.wait()
