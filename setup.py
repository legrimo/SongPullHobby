from setuptools import setup


setup(
    name="songpull-hobby",
    version="0.1.0",
    description="Sync Spotify playlist tracks and save matching YouTube links.",
    packages=["songpull_hobby"],
    python_requires=">=3.9",
    install_requires=[
        "python-dotenv>=1.0.1",
        "requests>=2.32.3",
        "rich>=13.7.1",
        "typer>=0.12.5",
        "urllib3<2",
    ],
    extras_require={"test": ["pytest>=8.0"]},
    entry_points={"console_scripts": ["songpull-hobby=songpull_hobby.cli:app"]},
)
