import pathlib
from setuptools import setup

# The directory containing this file
HERE = pathlib.Path(__file__).parent

# The text of the README file
DESCRIPTION = (HERE / "README.md").read_text()

# The text of the README file
REQUIRE = (HERE / "requirements.txt").read_text()

setup(
    name='krkn_ai',
    version='0.1',
    description='Krkn-AI',
    long_description=DESCRIPTION,
    long_description_content_type="text/markdown",
    platforms='any',
    classifiers=[
        "Operating System :: OS Independent",
        'Programming Language :: Python',
        "Programming Language :: Python :: 3",
        "Intended Audience :: Developers",
    ],
    packages=['krkn_ai'],
    include_package_data=True,
    install_requires=REQUIRE,
    entry_points={
        "console_scripts": [
            "krkn_ai = krkn_ai.cli:main",
        ]
    },
)