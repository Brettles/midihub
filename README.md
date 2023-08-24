## MIDI Hub

## Introduction

So you want to collaborate (musically) with someone on the other side of the internet. Turns out there is [a protocol for that](https://www.rfc-editor.org/rfc/rfc4695) with implementations for Mac (natively), [Windows](https://www.tobias-erichsen.de/software/rtpmidi.html) and [Linux](https://github.com/davidmoreno/rtpmidid). In theory, you spin up the RTP MIDI implementation of your choice and away you go.

But there will be bumps along the way if you intend on hosting your Internet-based MIDI host on a virtual machine. The first is that a sound card is required to make this work (more on this in a moment) - not an easy ask for a virtual machine. The second is that you'll need some sort of MIDI mixer/sequencer (that probably isn't the right term but go with me here) that allows you to connect MIDI sources and targets together. With a GUI there are a few options here ([Ableton](https://www.ableton.com/en/) is a good example for Mac) but your virtual machine may not have a GUI.

This (somewhat tiny!) repo is here to help. Especially if you want to do this with Linux.

Linux can solve the first problem (virtual sound card) by supplying a "dummy" sound card, even in a virtual server environment. Without this, most applications that use the [Alsa](https://wiki.archlinux.org/title/Advanced_Linux_Sound_Architecture) libraries won't work. That includes anything that wants to use MIDI. Even if you have the Alsa tools and libraries installed, if there isn't a sound card present then everything just fails.

The second problem is solve using Alsa as well - there is a command-line tool called `aconnect` which allows you to join those MIDI sources and targets with each other.

In this repo this is what you get:

 - midihub.py - Python script that launches `rtpmidid` and when participants join each channel (identified by UDP ports) it automatically joins those participants with each other. This can listen on one or more ports (typically starting at port 5004 and going up in increments of two - it's a defacto thing in the RTP MIDI world).
 - midihub-cloudformation.yml - [AWS CloudFormation](https://aws.amazon.com/cloudformation/) template for building an appropriate Linux instance and deploying into AWS. More details on that below.
 - lambda-midiHubParticipants.py and lambda-midiHubStats.py - These are the code for two Lambda functions which are automatically deployed by the CloudFormation template to respond to request when asked for participant and latency information. If you're not deploying this using CloudFormation you can use this code to query the database.
 - midihub.html and participants.html - Source HTML files for a (very simple!) web front end to call the two Lambda functions via API Gateway. Feel free to modify these or embed the code into your own web page. Designed to show who is connected and what their round-trip latency is. These are modified during setup with the appropriate API Gateway endpoint.
 - update-latency.py and update-participants.py - Two scripts that run on the instance. They trawl the log files from `rtpmidid` and send the contents to a DynamoDB database. Scheduled to run via cron once every minute.
 - create-s3-bucket.py - After the instance has been created this runs to create a S3 bucket with a unique name; link the CloudFront distirbution to it; set up secure access (S3 is not public; only CloudFront can access it); and uploads the HTML files after modifying them with the API Gateway endpoint URL. Note that if you are not deploying in the `us-east-1` region it make take some time (hours) for the CloudFront/S3 pair to work correctly.

The intention is that you can run this solution when you need it and shut it down when you don't. To shut the solution down, you can go into the [EC2 console](https://ap-southeast-1.console.aws.amazon.com/ec2/), select the instance labelled `midiHub` then choose "Instance state" (top-right of the browser window) and click "Stop instance". You'll notice there is a "Start instance" choice there too - that's how you can restart the virtual machine running MidiHub.

If you choose "Terminate instance" then everything will be deleted - you'll have to deploy it again (see the instructions in the next section). Terminating the instance will mean that you are not paying anything while you are not using it. When it is in a "stopped" state you will be charge a little for the persitent storage - about US$0.10 (that's ten cents) per month.

EC2 instance pricing [can be found here](https://aws.amazon.com/ec2/pricing/on-demand/) - for most purposes the t3 instances will be fine - other instance types offer higher CPU speeds and better networking performance. MIDI is pretty low network usage so those should not be required. Other costs will be [API Gateway](https://aws.amazon.com/api-gateway/pricing/), [Lambda](https://aws.amazon.com/lambda/pricing/), [S3](https://aws.amazon.com/s3/pricing/) and [Global Accelerator](https://aws.amazon.com/global-accelerator/pricing/). Out of all of these, EC2 and Global Accelerator will be the majority of the AWS charges.

## Deploy the CloudFormation template

To deploy in AWS, go to the [CloudFromation console](https://ap-southeast-1.console.aws.amazon.com/cloudformation/) and make sure you're deploying in the right AWS region. Typically you want to choose the region which is the lowest latency (over the internet) between all of the participants and that region. Then choose "Create stack" and when asked, upload the template file from this repo.

You'll be asked for the instance type 

The template assumes that your account has a default VPC which hasn't been modified - it will have a default public subnet with an Internet Gateway. Most accounts will have this (it is the default after all) but if you don't you'll need to modify the template to use a specific VPC.

The template creates:

 - an EC2 instance
 - an EC2 instance profile and an IAM role
 - a Security Group
 - an Elastic IP
 - a Global Acceelerator linked to the Elastic IP
 - a dummy CloudFront distribution that gets modified by the `create-s3-bucket.py` script
 - an API Gateway
 - two Lambda functions
 - a DynamoDB database
 - and a bunch of glue to hold all of these things together.

Deployment takes around ten minutes - there are a bunch of packages to install and the [rtpmidid]((https://github.com/davidmoreno/rtpmidid)) has to be compiled from source.  Note that when the CloudFormation service says that deployment is complete, you will need to wait for the rest of the tasks on the instance (such as the compilation) to complete.

Note that the name of the CloudFormation stack that you deploy should be unique if you are going to deploy MidiHub in multiple regions. For example "MidiHub-Sydney" and another "MidiHub-Singapore". This will prevent global resource name conflicts.

Outputs from the CloudFormation template of interest are:

 - The Elastic IP that you should use to connect to midiHub.
 - The two IP addresses for Global Accelerator (more on that below).
 - A CloudFront URL which will show recent latency statistic from clients that have connected to midiHub.
 - A CloudFront URL which will current participants on the hub.
 - The Lambda Function URL for retrieiving latency statistics and another for participants. These are generally not required (as the web page is built automatically) but you might need it if you were going to display the statistics using some other tool that you can build yourself.

The Elastic IP may result in charges to your account. If you are shutting down the MidiHub instance to save costs (this is a good idea!) you will be charged for the Elastic IP because it is unused. On [the pricing page](https://aws.amazon.com/ec2/pricing/on-demand/#Elastic_IP_Addresses) you can see that this will result in an extra charge of around US$4 per month. You can delete the entire CloudFormation stack (which will eliminate the charge) but the next time you create the stack it will have a new Elastic IP.

Finally, the Global Accelerator endpoint may give you better performance (in the form of lower latency) to connect to the hub. You should test using the Elastic IP and the Global Accelerator IPs. Use whichever one is lower.

## Deploy manually (in AWS or not)

You might want to run this on your own (non-AWS) virtual machine. In AWS this runs on Ubuntu so the package list below is based on that.

You'll need the following packages installed:

- python3-pip
- cmake
- g++
- pkg-config
- libavahi-client-dev
- libfmt-dev
- alsa-utils
- alsa-base
- libghc-alsa-core-dev
- avahi-utils 
- linux-modules-extra-\`uname -r\` - one of the prerequisites is the dummy sound card; it is this package in Ubuntu which installs it

Install the Python `boto3` library (`sudo pip3 install boto3`) - this is used in AWS to determine which region the software is running in; outside of AWS it doesn't matter but it is included so installing boto3 will avoid any errors.

Download and build `rtpmidid` from https://github.com/davidmoreno/rtpmidid

Download `midihub.py` and put it somewhere that you can run it. In AWS this is triggered every minute by cron - it automatically detects if it is still running and self-terminates if so. The running version starts `rtpmidid` and uses `aconnect` to join the MIDI sessions together. Options for where to find binaries are in `midihub.py`.

It's up to you whether you display the statistic or not. The `update-latency.py` and `update-participants.py` scripts can help here. They put the data into DynamoDb - you can use a different database if you like.
