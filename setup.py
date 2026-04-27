import pathlib
from setuptools import setup, find_packages

# The directory containing this file
HERE = pathlib.Path(__file__).parent

# The text of the README file (read as UTF-8 to avoid Windows encoding errors)
DESCRIPTION = (HERE / "README.md").read_text(encoding="utf-8")

# The text of the requirements file
REQUIRE = (HERE / "requirements.txt").read_text(encoding="utf-8")

setup(
    name="krkn_ai",
    version="0.0.3",
    description="Krkn-AI",
    long_description=DESCRIPTION,
    long_description_content_type="text/markdown",
    platforms="any",
    classifiers=[
        "Operating System :: OS Independent",
        "Programming Language :: Python",
        "Programming Language :: Python :: 3",
        "Intended Audience :: Developers",
    ],
    packages=find_packages(include=["krkn_ai*"]),
    include_package_data=True,
    install_requires=REQUIRE,
    entry_points={
        "console_scripts": [
            "krkn_ai = krkn_ai.cli:main",
        ]
    },
)
