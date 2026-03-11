from setuptools import setup, find_packages

setup(
    name="claude-spend",
    version="1.0.0",
    packages=find_packages(),
    install_requires=[
        "textual>=0.47.0",
        "textual-plotext>=0.2.0",
        "plotext>=5.2.0",
    ],
)
