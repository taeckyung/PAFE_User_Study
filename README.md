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

   1. You can get Conda by installing [Anaconda](https://www.anaconda.com/) first. 
   
   2. We share our python environment that contains all required python packages. Please refer to the `./pafe_app.yaml` file.
   
   3. You can import our environment using Conda:

   > $ conda env create -f pafe_app.yaml -n pafe_app

   Reference: https://docs.conda.io/projects/conda/en/latest/user-guide/tasks/manage-environments.html#creating-an-environment-from-an-environment-yml-file

3. (Optional) If you plan to use Youtube links, install a modified version of pafy, which retrieves Youtube URLs.
   > $ pip install git+https://github.com/Cupcakus/pafy


## How to Compile an Executable
! We are currently fixing the bug that libraries are not properly linked.

1. Please check configurations (e.g., paths) in `main.spec`.
2. Run main.spec:
> $ pyinstaller main.spec
3. Locate `./dist/main.exe` for the output.



## How to Customize
- Most of the configurations are done in `./main.py`, while compiling options are configured in `./main.spec`.
- (Example) Modify video URL (local file / URL): `Line #529 at ./main.py`
  - Initial version includes one demo video and one main video. 
  - The only difference is that if you do not respond to the ding sound in the demo video, it will stop running the video.  However, the main video will not stop even if you do not respond.
  - If you use local file, your file location should be located in the `./resources` folder.


## Citation
```
Taeckyung Lee, Dain Kim, Sooyoung Park, Dongwhi Kim, and Sung-Ju Lee. Predicting Mind-Wandering with Facial Videos in Online Lectures. In Proceedings of the IEEE/CVF Conference on Computer Vision and Pattern Recognition (CVPR) Workshops, June 2022.
```