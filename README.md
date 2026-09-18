# timon
<img src="src/timon/app/static/img/wheel1.svg" alt="A ship's wheel" height="120">

**t**oolkit of **i**ntegrated **m**icrobi**o**me analysis with support for lo**n**g reads.

timon is a local GUI made to prepare and launch nextflow pipelines. It now supports :
   - [roshab-cli](https://github.com/dsamoht/roshab-cli)
   - [mag-ont](https://github.com/dsamoht/mag-ont)

## Requirements

- Python ≥ 3.10
- [Nextflow](https://www.nextflow.io/)
- [Docker](https://www.docker.com/products/docker-desktop/)


## Usage
```console
$ timon
timon 0.1.0 → http://127.0.0.1:54123   (Ctrl-C to quit)
```
The app will open at the specified adress.

## Test your setup

A new install can be checked before any real data use (this is not mandatory).

Select **roshab-cli** and press **quick test**, beside the workflow picker — no
sample sheet, no parameters, no databases to install first.

It runs the selected pipeline's own test profile, which fetches every files it needs. The whole chain is tested: nextflow, docker, the live console and results. It downloads a few hundred megabytes the first time and takes a few minutes to run. If everything runs succesfully, you are good to go on your data.


## Acknowledgment
##### drawing by: Raphaëlle B. Germain