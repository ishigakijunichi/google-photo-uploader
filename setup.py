from setuptools import setup, find_packages

setup(
    name="google_photos_uploader",
    version="0.1.0",
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    install_requires=[
        "google-auth-oauthlib",
        "google-auth",
        "google-api-python-client",
        "requests",
        "Pillow",
        "pygame",
        "opencv-python",
        "watchdog",
        "psutil",
    ],
    extras_require={
        "dev": [
            "black",
            "isort",
            "flake8",
            "mypy",
            "pytest",
        ],
    },
    entry_points={
        "console_scripts": [
            "google-photos-uploader=google_photos_uploader.cli:main",
        ],
    },
    python_requires=">=3.7",
    author="Junichi Ishigaki",
    author_email="your.email@example.com",
    description="Google Photos Uploader",
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    url="https://github.com/yourusername/google_photos_uploader",
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: End Users/Desktop",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
    ],
) 