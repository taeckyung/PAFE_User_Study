# Predicting Mind-Wandering with Facial Videos in Online Lectures
This is the Python implementation of the experiment program of PAFE (Predicting Mind-Wandering with Facial Videos in Online Lectures, CVPR Workshop 2022).

<!--[ [Paper](https://nmsl.kaist.ac.kr/projects/attention/) ]-->
[ [Website](https://nmsl.kaist.ac.kr/projects/attention/) ]

## Tested Environment
We tested our codes under this environment:
- OS: Windows 10, Windows 11
- Python: Python 3.9
- Screen: Up to 1920x1080


## Installation Guide

1. Install [VLC Media Player](https://www.videolan.org/).

2. We use [Conda environment](https://docs.conda.io/).

   1. You can get Conda by installing [Anaconda](https://www.anaconda.com/). Skip if you already have Conda installed. 
   
   2. We share our Conda environment that contains all Python packages, at `./pafe_app.yaml` file.
   
   3. You can import our environment using Conda:

   > $ conda env create -f pafe_app.yaml -n pafe_app

   Reference: https://docs.conda.io/projects/conda/en/latest/user-guide/tasks/manage-environments.html#creating-an-environment-from-an-environment-yml-file

3. (Optional) If you plan to use Youtube links, install a modified version of Pafy, which retrieves Youtube URLs. Existing public version of Pafy is outdated.
   > $ pip install git+https://github.com/Cupcakus/pafy


## How to Compile an Executable

1. Please check configurations (e.g., paths) in `main.spec`.
2. Run main.spec:
> $ pyinstaller main.spec
3. Copy your `./resources` folder into `./dist` folder (`./dist/resources`)
4. You can compress the entire `./dist` folder, move it to any Windows machine, and execute `main.exe`.



## How to Customize
- Most of the configurations are done in `./main.py` while compiling options are configured in `./main.spec`.
- (Example) Modify video URL (local file URI / Youtube link): `Line #529 at ./main.py`
  - Initial version includes one demo video and one main video. 
  - The demo video stops and warns if a participant does not respond to the probing sound. However, the main video does not stop.
  - If you use a local file URI, your file location should be located in the `./resources` folder (as well as copied `./dist/resouces` folder).


## License
- This project is licensed under the terms of the MIT license.
- `./utils/vlc.py` follows its own license.
- Media (ding sound, keyboard sound) in the `./resources` folder are from https://freesound.org/, with [Creative Commons 0 License](https://creativecommons.org/publicdomain/zero/1.0/).
- Roboto font is licensed under the [Apache License, Version 2.0](http://www.apache.org/licenses/LICENSE-2.0).

## Citation

Taeckyung Lee, Dain Kim, Sooyoung Park, Dongwhi Kim, and Sung-Ju Lee. Predicting Mind-Wandering with Facial Videos in Online Lectures. _In Proceedings of the IEEE/CVF Conference on Computer Vision and Pattern Recognition (CVPR) Workshops_, June 2022.
