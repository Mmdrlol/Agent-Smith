*This activity has been created as part of the 42 curriculum by julhuang*

## Description
This activity consist of creating an llm that can send python code within a
sandbox, explore files using a mcp server and then iterate over the answer of
the sandbox to fix bugs for swe-bench or write functions for mbpp.

## Instructions
After dumping a task from the moulinette (commands in the moulinette's readme),
some default commands are provided with the Makefile such as `make mbpp` for
mbpp tasks or `make swebench` for swe-bench tasks. `make sandbox` also
launches the sandbox with the mcp server in stdio.
Otherwise, the available commands are:
`uv run python -m agent_mbpp ...`
`uv run python -m agent_swebench ...`
`uv run python -m sandbox ...`

## Resources
I did a bunch of online researches because a lot of python concepts wasn't
familiar to me, such as async and pipes. However, this time, I used an llm to
help me understand how to set up docker inside python, as well as how to use
the api, and help me with some parts of the code. I also used it to help me
write the prompt for the llm, but when it comes to the code, everything has
been written by me.

## System architecture
My code is composed of different modules managing different part of the system,
such as the llm, the sandbox, the mcp server and the benchmark tests for mbpp
and swe-bench.

## Agent loop explanation
My code follows the Thought -> Code -> Observation loop. I first giv ethe agent
the system prompt as well as the task to acheive, and it then produces an
answer that is then parsed and feeded into the sandbox and potentially the
mcp server, then the answer of the sandbox is captured and given as a user
message to the llm again.


## Sandbox design
My sandbox is just a seperate process that is executing the provided code using
exec, and all most of the security implementations simply comes from a custom
namespace I created to limit the imports, builtins and files access.
Networking and memory restrictions are directly done on the sandbox process
all together, and timeout is controled by the parent process, that shutdown
the child process is the max time is reached.


## Tool implementation details
Tools are implemented inside the mcp server and then exposed as python
functions inside the sandbox. The manual for all available tools is dynamically
created based on information received by the mcp server. Finally, a lot of
tools have been desabled for mbpp and `run_test` as been overwritten for
swe-bench to execute the `eval_script` inside the docker container.


## Benchmark results and analysis
The benchmark I did on swe-bench tasks shows that qwen3.6-27b was actually more
efficient for swe-tasks than gpt-oss-120b. The reason is that on swe-bench,
I couldn't manage to stop gpt-oss-120b from hallucinating Observations, making
tons of assumptions and outputing way long answers, no matter what I tried in
the system prompt, and even though it still does manage to recalibrate itself
at the end, it end up being way less efficient than qwen3.6-27b which was way
more direct and simplistic. gpt-oss-120b is still really good for mbpp tasks
so I kept it for this benchmark.


## Notes
At the time I am pushing this project, there are some bugs crashing the
moulinette and the eval script, stopping me from doing the reviews.
However, I managed to solve all the issues so here is how to fix them:
First, the moulinette doesn't manage to install its packages because of the
version of python, being now at 3.14. In order to solve it, simply use another
python version as follows:
```bash
uv python install 3.13
uv sync --python 3.13
```
then, for it to run properly, start podman (used for docker) with:
```bash
systemctl --user start podman.socket
```

Now, the evaluation code for the validate command for mbpp will crash because
the docker image used to launch it will be missing. So install it with:
```bash
docker pull python:3.11-slim
```
or whatever other version the evaluation code may be using.


And finally, for the validate command for swebench, the evaluation code will
also break and it seems to also be due to podman. However, the only way I found
to solve this issue is to delete the import of the function
`copy_to_container` inside:
```
moulinette/swebench/interact.py
```
with this function below:
```python
def copy_to_container(container, source, destination):
    result = subprocess.run(
        [
            "docker",
            "cp",
            str(source),
            f"{container.id}:{destination}",
        ],
        capture_output=True,
        text=True,
    )
```
And normally if I'm not forgetting anything, this should be all the fixes
needed to make everything work for the review.
