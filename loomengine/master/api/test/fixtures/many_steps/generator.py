import copy

template = {
    "fixed_inputs": [
        {
            "channel": "delimiter", 
            "data": {
                "contents": " "
            }, 
            "type": "string"
        }
    ], 
    "name": "many_steps", 
    "outputs": [
        {
            "channel": "count", 
            "type": "string"
        }
    ],
    'steps': []
}

def make_many_steps(count):
    t = copy.deepcopy(template)
    for i in range(1, count+1):
        t['steps'].append(
            {
                "command": "cat %s{{delimiter}} > {{n%s_out}}" % (i, i),
                "environment": {
                    "docker_image": "ubuntu"
                }, 
                "inputs": [
                    {
                        "channel": "delimiter", 
                        "type": "string"
                    }
                ], 
                "name": "n%s" % i, 
                "outputs": [
                    {
                        "channel": "n%s_out" % i,
                        "source": {
                            "stream": "stdout"
                        }, 
                        "type": "string"
                    }
                ], 
                "resources": {
                    "cores": 1, 
                    "disk_space": 1, 
                    "memory": 1
                }
            }
        )

    t['steps'].append(
        {
            "name": "join", 
            'command': 'echo '+''.join(
                ['{{n%s_out}}' % i for i in range(1,count+1)]),
            "environment": {
                "docker_image": "ubuntu"
            }, 
            'inputs': [{'channel': 'n%s_out' % i,
                        'type': 'string'} for i in range(1,count+2)],
            "outputs": [
                {
                    "channel": "count", 
                    "source": {
                        "stream": "stdout"
                    }, 
                    "type": "string"
                }
            ], 
            "resources": {
                "cores": 1, 
                "disk_space": 1, 
                "memory": 1
            }
        })

    return t
