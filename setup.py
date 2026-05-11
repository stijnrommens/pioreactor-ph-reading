# -*- coding: utf-8 -*-
from __future__ import annotations

from setuptools import find_packages
from setuptools import setup


setup(
    name="pioreactor-ph-reading",
    version="0.2.0",
    license="MIT",
    description="Read pH data.",
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    author_email="stijn.rommens@kuleuven.be",
    author="Stijn Rommens, VIB/KU Leuven",
    url="https://github.com/stijnrommens/pioreactor-ph-reading",
    packages=find_packages(),
    include_package_data=True,
    entry_points={"pioreactor.plugins": "pioreactor_ph_reading = pioreactor_ph_reading"},
)
