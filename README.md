## Overview

The **FMBench Orchestrator** enables the LLM benchmarking of latency, cost and accuracy across various serving stacks and models. It is built with moduler design where users can plug and play with any combination of:  
![Accuracy trajectory with prompt size](img/fmbench_conceptual_modules.png)

## Prerequisites

- **IAM ROLE**: You need an active AWS account having an **IAM Role** necessary permissions to create, manage, and terminate EC2 instances. See [this](docs/iam.md) link for the permissions and trust policies that this IAM role needs to have. Call this IAM role as `fmbench-orchestrator`.

- **Service quota**: Your AWS account needs to have enough **VCPU quota** limits to be able to start the Amazon EC2 instances that you may want to use for benchmarking. This may require you to submit service quota increase requests, use [this link](https://docs.aws.amazon.com/servicequotas/latest/userguide/request-quota-increase.html) for submitting a service quota increase requests. 

- **EC2 Instance**: It is recommended to run the orchestrator on an EC2 instance, attaching the IAM Role with permissions, preferably located in the same AWS region where you plan to launch the multiple EC2 instances (although launching instances across regions is supported as well).

    - Use `Ubuntu` as the instance OS, specifically the `ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-amd64-server-20240927` AMI.
    - Use `t3.xlarge` as the instance type with preferably at least 100GB of disk space.
    - Associate the `fmbench-orchestrator` IAM role with this instance.


## Installation

1. **Install `conda`**

    ```{.bash}
    wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh
    bash Miniconda3-latest-Linux-x86_64.sh -b  # Run the Miniconda installer in batch mode (no manual intervention)
    rm -f Miniconda3-latest-Linux-x86_64.sh    # Remove the installer script after installation
    eval "$(/home/$USER/miniconda3/bin/conda shell.bash hook)" # Initialize conda for bash shell
    conda init  # Initialize conda, adding it to the shell
    ```

1. **Clone the Repository**

    ```bash
    git clone https://github.com/awslabs/fmbench-orchestrator.git
    cd fmbench-orchestrator
    ```

### Conda Environment Setup

1. **Create a Conda Environment with Python 3.11**:

    ```bash
    conda create --name fmbench-orchestrator-py311 python=3.11 -y
    ```

1. **Activate the Environment**:

    ```bash
    conda activate fmbench-orchestrator-py311
    ```

1. **Install Required Packages**:

    ```bash
    pip install -r requirements.txt
    ```

1. **Hugging Face token**:
   Please follow the instructions [here](https://huggingface.co/docs/hub/security-tokens) to get a Hugging Face token.
   Please also make sure to get **access to the models in HuggingFace**. 
   Most models and tokenizers are downloaded from Hugging Face, to enable this place your Hugging Face token in `/tmp/hf_token.txt`.

   ```bash
   # replace with your Hugging Face token
   hf_token=your-hugging-face-token
   echo $hf_token > /tmp/hf_token.txt
   ```

### Run an example experiment:
In this experiment, we compare the price performance of running Llama3.1-8b on EC2 g6e.2xlarge and g6e.4xlarge.

```bash
python main.py --config-file configs/ec2.yml
```

Here is a description of all the command line parameters that are supported by the orchestrator:

- **--config-file** - _required_, path to the orchestrator configuration file.
- **--ami-mapping-file** - _optional_, _default=ami_mapping.yml_, path to a config file containing the region->instance type->AMI mapping
- **--fmbench-config-file** - _optional_, config file to use with `FMBench`, this is used if the orchestrator config file uses the "{{config_file}}" format for specifying the `FMBench` config file. If you are benchmarking on SageMaker or Bedrock then parameter does need to be specified.
- **--infra-config-file** - _optional_, _default=infra.yml_, config file to use with AWS infrastructure
- **--write-bucket** - _optional_, _default=placeholder_, *this parameter is only needed when benchmarking on SageMaker*, Amazon S3 bucket to store model files for benchmarking on SageMaker

### Analyze the results

To analyze the results from the above experiment: 

```{.bashrc}
python analytics/analytics.py --results-dir results/llama3-8b-g6e --model-id llama3-8b --payload-file payload_en_3000-3840.jsonl --latency-threshold 2
```
The results are saved in `fmbench-orchestrator/analytics/results/llama3-8b-g6e/`, including summaries of the results and a heatmap that helps understand which instance type gives the best price performance at the desired scale (transactions/minute) while maintaining the inference latency below a desired threshold.
Below is one of the output tables about cost comparison. 
![example_orchestrator_cost_comparison](docs/img/example_orchestrator_cost_comparison.png)


## How do I ...

See [configuration guide](docs/config_guide.md) for details on the orchestrator config file.

### Benchmark for EC2

Take an existing config file from the [`configs`](configs/) folder, create a copy and edit it as needed. You would typically only need to modify the `instances` section of the config file to either modify the instance type and config file or add additional types. For example the following command line benchmarks the `Llama3.1-8b` models on `g6e` EC2 instance types.

```bash
python main.py --config-file configs/ec2.yml
```

## Benchmark for SageMaker

You can benchmark any model(s) on Amazon SageMaker by simply pointing the orchestrator to the desired `FMBench` SageMaker config file. The orchestrator will create an EC2 instance and use that for running `FMBench` benchmarking for SageMaker. For example the following command line benchmarks the `Llama3.1-8b` models on `ml.g5` instance types on SageMaker.

```bash
# provide the name of an S3 bucket in which you want
# SageMaker to store the model files (for models downloaded
# from Hugging Face)
write_bucket=your-bucket-name
python main.py --config-file configs/sagemaker.yml --fmbench-config-file fmbench:llama3.1/8b/config-llama3.1-8b-g5.2xl-g5.4xl-sm.yml --write-bucket $write_bucket
```

## Benchmark for Bedrock

You can benchmark any model(s) on Amazon Bedrock by simply pointing the orchestrator to the desired `FMBench` SageMaker config file. The orchestrator will create an EC2 instance and use that for running `FMBench` benchmarking for Bedrock.  For example the following command line benchmarks the `Llama3.1` models on Bedrock.

```bash
python main.py --config-file configs/bedrock.yml --fmbench-config-file fmbench:bedrock/config-bedrock-llama3-1.yml
```

### Use an existing `FMBench` config file but modify it slightly for my requirements

1. Download an `FMBench` config file from the [`FMBench repo`](https://github.com/aws-samples/foundation-model-benchmarking-tool/tree/main/src/fmbench/configs) and place it in the [`configs/fmbench`](./configs/fmbench/) folder.
1. Modify the downloaded config as needed.
1. Update the `instance -> fmench_config` section for the instance that needs to use this file to point to the updated config file in `fmbench/configs` so for example if the updated config file was `config-ec2-llama3-8b-g6e-2xlarge-custom.yml` then the following parameter:

    ```{.bashrc}
    fmbench_config: 
    - fmbench:llama3/8b/config-ec2-llama3-8b-g6e-2xlarge.yml
    ```
      would be changed to:

    ```{.bashrc}
    fmbench_config: 
    - configs/fmbench/config-ec2-llama3-8b-g6e-2xlarge-custom.yml
    ```

    The orchestrator would now upload the custom config on the EC2 instance being used for benchmarking.

### Provide a custom prompt/custom tokenizer for my benchmarking test

The `instances` section has an `upload_files` section for each instance where we can provide a list of `local` files and `remote` directory paths to place any custom file on an EC2 instance. This could be a `tokenizer.json` file, a custom prompt file, or a custom dataset. The example below shows how to upload a custom `pricing.yml` and a custom dataset to an EC2 instance.

```{.bashrc}
instances:
- instance_type: g6e.2xlarge
  <<: *ec2_settings
  fmbench_config: 
  - fmbench:llama3/8b/config-ec2-llama3-8b-g6e-2xlarge.yml
  upload_files:
   - local: byo_dataset/custom.jsonl
     remote: /tmp/fmbench-read/source_data/
   - local: analytics/pricing.yml
     remote: /tmp/fmbench-read/configs/
```

See [`ec2_llama3.2-1b-cpu-byodataset.yml`](configs/ec2_llama3.2-1b-cpu-byodataset.yml) for an example config file. This file refers to the [`synthetic_data_large_prompts`](byo_dataset/synthetic_data_large_prompts.jsonl) and a custom prompt file [`prompt_template_llama3_summarization.txt`](byo_dataset/prompt_template_llama3_summarization.txt) for a summarization task. You can edit the dataset file and the prompt template as per your requirements.

### Benchmark multiple config files on the same EC2 instance

Often times we want to benchmark different combinations of parameters on the same EC2 instance, for example we may want to test tensor parallelism degree of 2, 4 and 8 for say `Llama3.1-8b` model on the same EC2 machine say `g6e.48xlarge`. Can do that easily with the orchestrator by specifying a list of config files rather than just a single config file as shown in the following example:

   ```{.bashrc}
  fmbench_config: 
  - fmbench:llama3.1/8b/config-llama3.1-8b-g6e.48xl-tp-2-mc-max-djl.yml
  - fmbench:llama3.1/8b/config-llama3.1-8b-g6e.48xl-tp-4-mc-max-djl.yml
  - fmbench:llama3.1/8b/config-llama3.1-8b-g6e.48xl-tp-8-mc-max-djl.yml
  ```
The orchestrator would in this case first run benchmarking for the first file in the list, and then on the same EC2 instance run benchmarking for the second file and so on and so forth. The results folders and `fmbench.log` files for each of the runs is downloaded at the end when all config files for that instance have been processed.

## Contributing
Contributions are welcome! Please fork the repository and submit a pull request with your changes. For major changes, please open an issue first to discuss what you would like to change.


## Security

See [CONTRIBUTING](CONTRIBUTING.md#security-issue-notifications) for more information.

## License

This project is licensed under the MIT-0 License - see the [LICENSE](LICENSE) file for details.





# FMBench Orchestrator

![fmbench_architecture](docs/img/Fmbench-Orchestrator-Architecture-v1.png)








You can either use an existing config file included in this repo, such as [`configs/ec2.yml`](configs/ec2.yml) or create your own using the files provided in the [`configs`](configs) directory as a template. Make sure you are in the `fmbench-orchestrator-py311` conda environment. The following command runs benchmarking for the `Llama3-8b` model on an `g6e.2xlarge` and `g6e.4xlarge` instance types.

The following command runs benchmarking on an EC2 instance, see [Benchmark for SageMaker](#benchmark-for-sagemaker) for benchmarking on SageMaker and [Benchmark for Bedrock](#benchmark-for-bedrock) for benchmarking on Bedrock.
