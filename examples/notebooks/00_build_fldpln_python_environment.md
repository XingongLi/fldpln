# Build a Python Environment for Using the FLDPLN Model

In order to use the FLDPLN model, we need to have a Python environment with the necessary packages installed. This document provides information on how to build the "fldpln" Python environment and how to use it in JupyterLab and Visual Studio Code (VSC). This includes the following major steps:
* Create the fldpln Python environment and install some necessary Python packages.
* Install MATLAB Runtime and the FLDPLN model Python package ( fldpln_py) in the fldpln environment.
* Install the tiling and mapping Python package (fldpln) in the fldpln environment. 

## Create the fldpln Python Environment and Install Some Necessary Packages

### Install Miniconda

Miniconda is a lightweight version of Anaconda, which is a full-fledged data science platform. Miniconda only includes Python and conda, while Anaconda includes Python, conda, and a suite of other common used packages. If you already have Miniconda installed on your computer. You can skip the rest of this section.

* Go to the [Miniconda download page](https://docs.conda.io/en/latest/miniconda.html#windows-installers) and download the Miniconda installer for Windows or Unix depending the OS system of your computer. The web site provides the installer with the most recent Python version. This is fine as we can create a new Python environment with the desired Python version later.
* Run the installer and follow the instructions to install Miniconda on your computer. **Make sure to check the box during installation to add Miniconda to the system PATH so that you can use conda in the command prompt window.**

### Install Mamba for faster package installation

After installing miniconda, the base Python environment is created. In the base environment, we will install mamba, a faster and more efficient package manager than conda, using the following command:
```
conda install -c conda-forge mamba
```

### Create the environment and install packages using a YAML file

The fldpln Python environment has been exported as a YAML configuration file. So we can replicate the environment on your computer using the YAML file instead of installing the necessary packages one-by-one. 

Open a miniconda command line window (CLW) and in the base environment (by default), navigate to the folder where the .yaml file is saved, and run the following mamba command to create the fldpln environment:
```
mamba env create -f fldpln_windows.yaml
```
Installing all the necessary packages might take a surprisingly long time especially so be patient.

Note that different YAML files are needed for Windows and Unix-based systems. Two YAML files, fldpln_windows.yaml and fldpln_unix.yaml, are created for Windows and Unix-based systems respectively.

## Install FLDPLN Related Python Packages

Currently, there are two python packages are needed for using the FLDPLN model. The first is the fldpln_py Python package compiled from the FLDPLN model originally developed in MATLAB. The second is the fldpln package, which contains modules for running the FLDPLN model and for tiling and mapping FLDPLN libraries.  

### Install the fldpln_py Python Package

The FLDPLN model is originally developed in MATLAB and compiled into the fldpln_py Python package. The MATLAB compiled Python package can be installed and used on either Windows or Unix systems (though not tested on Unix system yet) with the MATLAB Runtime installed. Note that the MATLAB Runtime is free but required to use the compiled Python package.

#### Install MATLAB Runtime

Two kind of installers are available to install MATLAB Runtime and the fldpln_py package. The [smaller installer](https://github.com/XingongLi/fldpln/blob/main/fldpln_py/fldpln_py_Installer_web.exe) is available on Github download MATLAB Runtime on-the-fly during the installation and the [larger installer](https://itprdkarsap.home.ku.edu/download/fldpln/fldpln_py_installer_mcr.exe) available on KU KBS-KARS server has the Runtime included in the installer. Whichever installer is used, it will install the MATLAB Runtime and also unpack and save the fldpln_py package under the installation folder, typically under folder C:\Program Files\fldpln_py.

Note that the installer for Windows automatically sets the MATLAB Runtime path during installation, but on Linux or macOS you must add the Runtime manually. See [here](https://www.mathworks.com/help/compiler_sdk/cxx/mcr-path-settings-for-run-time-deployment.html) for more information.

#### Install the fldpln_py package in the fldpln environment

Installing fldpln_py package, we need to open a miniconda command line window as an administrator. In the window, we need to **activate the fldpln environment and navigate to the fldpln_py folder where file setup.py is located** (C:\Program Files\fldpln_py\application by default), and install the package using either one of the following commands. This procedure is necessary as the fldpln_py package is created by MATLAB as a special Python package.
```
python setup.py install
```
or
```
pip install .
```

### Install the fldpln Package

The [fldpln Python package](https://pypi.org/project/fldpln/) provides several modules to access the FLDPLN model within the fldpln_py package (model module) to create segment-based library and three additional modules (tile, mapping and gauge modules) to tile segment-based libraries and map flood inundation depth using the tiled libraries. The [documentation](https://xingongli.github.io/fldpln/) on those modules are available on GitHub. The package is published on PyPI and can be installed using:
```
pip install fldpln
``` 

## Using the fldpln Environment in Different Development Environments

The fldpln python environment can be used in different development environments including JupyterLab and Visual Studio Code (VSC).

### Use the fldpln environment in JupyterLab

To run the notebooks using JupyterLb,we need to first install the jupyterlab package into the fldpln environment. We need to open a miniconda command line window, activate the fldpln environment, and run the following command:
  ```
  mamba install -c conda-forge jupyterlab
  ```
After the installation and in the command line window, we can then navigate to the folder where the notebooks are located and run the following command to start JupyterLab in a web browser. Note the space between the two words.
```
jupyter lab
```
You can shutdown the local JupyterLab server by using "Ctrl + C" in the command window where you typed in the above command.

### Use the Environment in Visual Studio Code (VSC)

The fldpln environment should be directly available in VSC after for writing Python scripts and notebooks. Below are some trouble shooting steps if the environment is not available in VSC.
* Make sure the conda command is added to you computer system’s PATH environment variable so that VSC can use it to activate a specific python environment.
  * When installing miniconda, the default installation setting doesn’t add its miniconda executable path to the PATH environment variable.
  * This is can be done by using the Advanced System Settings in Control Panel (see the screenshot below)

    ![Setup PATH variable](./images/PATH_environment_variables.png)
* VSC terminal 
  * VSC uses powershell as the default terminal which cause some issues even after including conda path in the PATH environment variable.
  * A quick solution is to change the default powershell terminal in VSC to the regular cmd terminal by press CTRL+SHIFT+P in VSC and search for “terminal select default profile” and select “Command Prompt C:\WINDOWS\System32\cmd.exe”
* VSC also supports Jupyter notebooks. But it needs the ipython kernel package be installed into the environment. The kernel can also be installed when you open a notebook in VSC and choose the fldpln environment. You can also install the package into the fldpln environment by:
  ```
  mamba install -c conda-forge ipykernel
  ```