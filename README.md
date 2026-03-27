# Model-Compression Competition & Evaluation Bot

## Purpose

This repository hosts a Discord bot + evaluation pipeline for a model-compression / optimization competition.  
Participants submit their “optimized/compressed model”, and the bot evaluates how good the compression/optimization is by measuring:  
- model file size  
- parameter count  
- FLOPs (or MACs)  
- inference time (on standard input / benchmark data)  

The evaluation is done inside a Docker container to ensure uniform, reproducible environment.
