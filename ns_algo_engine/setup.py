from setuptools import setup, find_packages
from setuptools.command.install import install
import os
import subprocess
import sys

# Read requirements from requirements.txt
def read_requirements():
    requirements = []
    if os.path.exists('requirements.txt'):
        with open('requirements.txt', 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    requirements.append(line)
    return requirements

class PostInstallCommand(install):
    """Post-installation for installation mode."""
    def run(self):
        install.run(self)
        # Install all .tar.gz files from libs directory
        libs_dir = os.path.join(os.path.dirname(__file__), 'algo', 'libs')
        if os.path.exists(libs_dir):
            tar_files = [f for f in os.listdir(libs_dir) if f.endswith('.tar.gz')]
            if tar_files:
                print(f"Found {len(tar_files)} package(s) in libs directory...")
                for tar_file in tar_files:
                    tar_path = os.path.join(libs_dir, tar_file)
                    print(f"Installing {tar_file}...")
                    try:
                        subprocess.check_call([sys.executable, '-m', 'pip', 'install', tar_path])
                        print(f"{tar_file} installed successfully!")
                    except subprocess.CalledProcessError as e:
                        print(f"Warning: Failed to install {tar_file}: {e}")
            else:
                print("No .tar.gz packages found in libs directory")
        else:
            print(f"Warning: libs directory not found at {libs_dir}")

setup(
    name='ns_algo_engine',
    version='1.0.0',
    description='NS Algorithmic Trading Engine',
    author='NS',
    packages=find_packages(),
    install_requires=read_requirements(),
    python_requires='>=3.7',
    include_package_data=True,
    zip_safe=False,
    cmdclass={
        'install': PostInstallCommand,
    },
)
