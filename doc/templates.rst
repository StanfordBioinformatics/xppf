######################################
Loom Templates
######################################

To run an analysis on Loom, you must first have a template that defines the analysis steps and their relative arrangement (input/output dependencies, scatter-gather patterns). An analysis run may then be initiated by assigning input data to an existing template.

A Loom template is defined in a yaml or json file and then imported to the Loom server.

*********
Examples
*********

To run these examples, you will need access to a running Loom server. See :ref:`getting-started` for help launching a Loom server either locally or in the cloud.

join_two_words
==============

*simplest example*

This example illustrates the minimal set of features in a Loom template: name, command, environment (defined by a docker image), and input/output definitions.

We use the optional "data" field on the inputs to assign default values.

*join_two_words.yaml:*

.. literalinclude:: ../client/loomengine/examples/join_two_words/join_two_words.yaml

:download:`join_two_words.yaml <../client/loomengine/examples/join_two_words/join_two_words.yaml>`

The command "echo {{word1}} {{word2}}" makes use of Jinja2_ notation to substitute input values. "{{word1}}" in the command will be substituted with the value provided on the "word1" input channel. For inputs of type "string", "integer", "boolean", and "float", the value substituted is a string representation of the data. For inputs of type "file", the filename is substituted. The full set of Jinja2 features may be used, including filters, conditional statements, and loops.

.. _Jinja2: http://jinja.pocoo.org/docs/

**Run the join_two_words example**

::
   
   loom template import join_two_words.yaml
  
   # Run with default input data
   loom run start join_two_words
   
   # Run with custom input data
   loom run start join_two_words word1=foo word2=bar

capitalize_words
================

*array data, iterating over an array input*

This template illustrates the concept of non-scalar data (in this case a 1-dimensional array). The default mode for inputs is "no_gather", which means that rather than gather all the objects into an array to be processed together in a single task, Loom will iterate over the array and execute the command once for each data object, in separate tasks.

Here we capitalize each word in the array. The output from each task executed is a string, but since many tasks are executed, the output is an array of strings.

Note the use of "as_channel" on the input definition. Since our input channel is an array we named the channel with the plural "words", but this run executes a separate tasks for each element in the array it may be confusing to refer to "{{words}} inside the command. It improves readability to use "as_channel: word".

*capitalize_words.yaml:*

.. literalinclude:: ../client/loomengine/examples/capitalize_words/capitalize_words.yaml

:download:`capitalize_words.yaml <../client/loomengine/examples/capitalize_words/capitalize_words.yaml>`

**Run the capitalize_words example**

::
   
   loom template import capitalize_words.yaml
   
   # Run with default input data
   loom run start capitalize_words
   
   # Run with custom input data
   loom run start capitalize_words words=[uno,dos,tres]

join_array_of_words
===================

*array data, gather mode on an input*

Earlier we saw how to join two words, each defined on a separate input. But what if we want to join an arbitrary number of words?

This example has a single input, whose default value is an array of words. By setting the mode of this input as "gather", instead of iterating as in the last example we will execute a single task that receives the full list of words as an input.

In this example we merge the strings and output the result as a string.

*join_array_of_words.yaml:*

.. literalinclude:: ../client/loomengine/examples/join_array_of_words/join_array_of_words.yaml

:download:`join_array_of_words.yaml <../client/loomengine/examples/join_array_of_words/join_array_of_words.yaml>`

**Run the join_array_of_words example**

::
   
   loom template import join_array_of_words.yaml
   
   # Run with default input data
   loom run start join_array_of_words
   
   # Run with custom input data
   loom run start join_array_of_words wordarray=[uno,dos,tres]

split_words_into_array
======================

*array data, scatter mode on an output, output parsers*

This example is the reverse of the previous example. We begin with a scalar string of space-separated words, and split them into an array.

To generate an array output from a single task, we set the output mode to "scatter".

We also need to instruct Loom how to split the text in stdout to an array. For this we use a parser that uses the space character as the delimiter and trims any extra whitespace characters from the words.

*split_words_into_array.yaml:*

.. literalinclude:: ../client/loomengine/examples/split_words_into_array/split_words_into_array.yaml

:download:`split_words_into_array.yaml <../client/loomengine/examples/split_words_into_array/split_words_into_array.yaml>`

**Run the split_words_into_array example**

::
   
   loom template import split_words_into_array.yaml
   
   # Run with default input data
   loom run start split_words_into_array
   
   # Run with custom input data
   loom run start split_words_into_array text="one two three"

add_then_multiply
=================

*multistep templates, connecting inputs and outputs, custom interpreter*

All the previous examples have involved just one step. Here we show how to define more than one step in a template.

Also, since we are doing math in this example, it is easier to use python than bash, so we introduce the concept of custom interpreters.

Notice how the flow of data is defined using shared channel names between inputs and outputs. On the top-level template "add_then_multiply" we define input channels "a", "b", and "c". These are used by the steps "add" ("a" and "b") and "multiply" ("c"). There is also an output from "add" called "ab_sum" that serves as an input for "multiply". Finally, the output from "multiply", called "result" is passed up to "add_then_multiply" as a top-level output.

*add_then_multiply.yaml:*

.. literalinclude:: ../client/loomengine/examples/add_then_multiply/add_then_multiply.yaml

:download:`add_then_multiply.yaml <../client/loomengine/examples/add_then_multiply/add_then_multiply.yaml>`

**Run the add_then_multiply example**

::
   
   loom template import add_then_multiply.yaml
   
   # Run with default input data
   loom run start add_then_multiply
   
   # Run with custom input data
   loom run start add_then_multiply a=1 b=2 c=3
  
building_blocks
===============

*reusing templates*

Let's look at another way to write the previous workflow. The "add" and "multiply" steps can be defined as stand-alone workflows. After they are defined, we can create a template that includes those templates as steps.

*add.yaml:*

.. literalinclude:: ../client/loomengine/examples/building_blocks/building_blocks.yaml.dependencies/templates/add.yaml

*multiply.yaml:*

.. literalinclude:: ../client/loomengine/examples/building_blocks/building_blocks.yaml.dependencies/templates/multiply.yaml

*building_blocks.yaml:*

.. literalinclude:: ../client/loomengine/examples/building_blocks/building_blocks.yaml

:download:`add.yaml <../client/loomengine/examples/building_blocks/building_blocks.yaml.dependencies/templates/add.yaml>`

:download:`multiply.yaml <../client/loomengine/examples/building_blocks/building_blocks.yaml.dependencies/templates/multiply.yaml>`

:download:`building_blocks.yaml <../client/loomengine/examples/building_blocks/building_blocks.yaml>`

**Run the building_blocks example**

::
   
   # Import the parent template along with any dependencies
   loom template import building_blocks.yaml
   
   # Run with default input data
   loom run start building_blocks
   
   # Run with custom input data
   loom run start building_blocks a=1 b=2 c=3

search_file
===========

*file inputs*

Most of these examples use non-file inputs for convenience, but files can be used as inputs and outputs much like other data types.

In this example, the "lorem_ipsum.txt" input file should be imported prior to importing the "search_file.yaml" template that references it.

*lorem_ipsum.txt:*

.. literalinclude:: ../client/loomengine/examples/search_file/search_file.yaml.dependencies/files/lorem_ipsum.txt

*search_file.yaml:*

.. literalinclude:: ../client/loomengine/examples/search_file/search_file.yaml

:download:`lorem_ipsum.txt <../client/loomengine/examples/search_file/search_file.yaml.dependencies/files/lorem_ipsum.txt>`
		    
:download:`search_file.yaml <../client/loomengine/examples/search_file/search_file.yaml>`

Here is an alternative text file not referenced in the template. We can override the default input file and specify beowulf.txt as the input when starting a run.

*beowulf.txt:*

.. literalinclude:: ../client/loomengine/examples/search_file/beowulf.txt

:download:`beowulf.txt <../client/loomengine/examples/search_file/beowulf.txt>`
	  
**Run the search_file example**

::
   
   # Import the template along with dependencies
   loom template import search_file.yaml
   
   # Run with default input data
   loom run start search_file
   
   # Run with custom input data
   loom file import beowulf.txt
   loom run start search_file pattern=we file_to_search=beowulf.txt\$20b8f89484673eae4f121801e1fec28c

word_combinations
=================

*scatter-gather, input groups, output mode gather(n)*

When a template step has two inputs rather than one, iteration can be done in two ways:

* collated iteration: [a,b] + [c,d] => [a+c,b+d]
* combinatorial iteration: [a,b] + [c,d] => [a+c, a+d, b+c, b+d]

With more than two inputs, we could employ some combination of these two approaches.

"groups" provide a flexible way to define when to use collated or combinatorial iteration. Each input has an integer group ID (the default is 0). All inputs with a common group ID will be combined with collation. Between groups, combinatorial iteration is used.

In this example, we iterate over two inputs, one with an array of adjectives and one with an array of nouns. Since the inputs have different group IDs, we iterate over all possible combinations of word pairs (combinatorial).

*word_combinations.yaml:*

.. literalinclude:: ../client/loomengine/examples/word_combinations/word_combinations.yaml

:download:`word_combinations.yaml <../client/loomengine/examples/word_combinations/word_combinations.yaml>`

You may have noticed that we gather the input "word_pair_files" with "mode: gather(2)". This is because word_pair_files is not just an array, but an array of arrays. We wish to gather it to full depth. You may wish to modify this example to use "mode: gather" (or equivalently "mode: gather(1)") to see how it affects the result.

**Run the word_combinations example**

::
   
   loom template import word_combinations.yaml

   # Run with default input data
   loom run start word_combinations
   
   # Run with custom input data
   loom run start word_combinations adjectives=[little,green] nouns=[men,pickles,apples]

sentence_scoring
================

*nested scatter-gather*

Why should we bother differentiating between "gather" and "gather(2)"? This example illustrates why, by showing how to construct a scatter-scatter-gather-gather workflow. On the first gather, we do not fully gather the results into an array, but only gather the last level of nested arrays. This lets us group data for the letters in each word while keeping data for different words separate. On the second gather, we combine the data for each word to get an overall result for the sentence.

*sentence_scoring.yaml:*

.. literalinclude:: ../client/loomengine/examples/sentence_scoring/sentence_scoring.yaml

:download:`sentence_scoring.yaml <../client/loomengine/examples/sentence_scoring/sentence_scoring.yaml>`

**Run the sentence_scoring example**

::
   
   loom template import sentence_scoring.yaml
   
   # Run with default input data
   loom run start sentence_scoring
   
   # Run with custom input data
   loom run start sentence_scoring sentence='To infinity and beyond'

*****************
Special functions
*****************

The examples above demonstrated how jinja template notation can be used to incorporate input values into commands, e.g. "echo {{input1}}". The template context contains all input channel names as keys, but it also contains the special functions below.

If an input uses the same name as a special function, the input value overrides.

index
=====
*index[i]* returns the one-based index of the current task. So if a run contains 3 parallel tasks, *index[1]* will return value 1, 2, or 3 for the respective tasks. If the run contains nested parallel tasks, *index[i]* will return the index of the task in dimension *i*. If *i* is a positive integer larger than the dimensionality of the tasks, it will return a default value of 1  (e.g. *index[1]*, *index[2]*, etc. all return 1 for scalar data.). If *i* is not a positive integer value, a validation error will result.

size
====
*size[i]* returns the size of the specified dimension. So if a run contains 3 parallel tasks, *size[1]* will return a value of 3 for all tasks. If the run contains nested parallel tasks, *size[i]* will return the size of dimension *i*. If *i* is a positive integer larger than the dimensionality of the tasks, it will return a value of 1 (e.g. *size[1]*, *size[2]*, etc. all return 1 for scalar data). If *i* is not a positive integer value, a validation error will result.

*******
Schemas
*******

Template schema
===============

============  ========  =======================  =================  ===============
field         required  default                  type               example
============  ========  =======================  =================  ===============
name          yes                                string             'calculate_error'
inputs        no        []                       [Input]            ['channel': 'input1', 'type': 'string']
outputs       no        []                       [Output]           ['channel': 'output1', 'type': 'string', 'source': {'stream': 'stdout'}]
command*      yes                                 string            'echo {{input1}}'
interpreter*  no        /bin/bash -euo pipefail  string             '/usr/bin/python'
resources*    no        null
environment*  yes                                string             {'docker_image': 'ubuntu:latest'}
steps+        no        []                       [Template|string]  see examples in previous section
============  ========  =======================  =================  ===============

\* only on executable steps (leaf nodes)

\+ only on container steps (non-leaf nodes)

Input schema
============

============  ========  =======================  =================  ===============
field         required  default                  type               example
============  ========  =======================  =================  ===============
channel       yes                                string             'sampleid'
type          yes                                string             'file'
mode*         no        no_gather                string             'gather'
group*        no        0                        integer            2
hint          no                                 string             'Enter a quality threshold'
data          no        null                     DataNode           {'contents': [3,7,12]}
============  ========  =======================  =================  ===============

\* only on executable steps (leaf nodes)

DataNode schema
===============

============  ========  =======================  =================  ===============
field         required  default                  type               example
============  ========  =======================  =================  ===============
contents      yes                                                   see notes below
============  ========  =======================  =================  ===============

DataNode contents can be a valid data value of any type. They can also be a list, or nested lists of any of these types, provided all items are of the same type and at the same nested depth.

=========  ================================================  ==================================
data type  valid DataNode contents examples                  invalid DataNode contents examples
=========  ================================================  ==================================
integer    172
float      3.98
string     'sx392'
boolean    true             
file       myfile.txt
file       myfile.txt$9dd4e461268c8034f5c8564e155c67a6
file       $9dd4e461268c8034f5c8564e155c67a6
file       myfile.txt\@ef62b731-e714-4b82-b1a7-057c1032419e
file       myfile.txt\@ef62b7
file       \@ef62b7
integer    [2,3]
integer    [[2,2],[2,3,5],[17]]
integer                                                      [2,'three'] (mismatched types)
integer                                                      [[2,2],[2,3,[5,17]]] (mismatched depths)
=========  ================================================  ==================================

Output schema
=============

============  ========  =======================  =================  ===============
field         required  default                  type               example
============  ========  =======================  =================  ===============
channel       yes                                string             'sampleid'
type          yes                                string             'file'
mode\*         no        no_gather                string             'gather'
parser\*       no        null                     OutputParser       {'type': 'delimited', 'options': {'delimiter': ','}
source\*       yes                                OutputSource       {'glob': '\*.dat'}
============  ========  =======================  =================  ===============

\* only on executable steps (leaf nodes)

OutputParser schema
===================

============  ========  =======================  =================  ===============
field         required  default                  type               example
============  ========  =======================  =================  ===============
type\*         yes                                string             'delimited'
options       no                                 ParserOptions      {'delimiter':' ','trim':true}
============  ========  =======================  =================  ===============

\* Currently "delimited" is the only OutputParser type

OutputSource schema
===================

============  ========  =======================  =================  ===============
field         required  default                  type               example
============  ========  =======================  =================  ===============
filename\*     false                              string             'out.txt'
stream\*       false                              string             'stderr'
glob+         false                              string             '\*.txt'
filenames+    false                              string             ['out1.txt','out2.txt']
============  ========  =======================  =================  ===============

\* When used with outputs with "scatter" mode, an OutputParser is required

\+ Only for outputs with "scatter" mode. (No parser required.) The "glob" field supports "\*", "\?", and character ranges using "[]".
