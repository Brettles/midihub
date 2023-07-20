## MIDI Hub

## Introduction

So you want to collaborate (musically) with someone on the other side of the internet. Turns out there is [a protocol for that](https://www.rfc-editor.org/rfc/rfc4695) with implementations for Mac (natively), [Windows](https://www.tobias-erichsen.de/software/rtpmidi.html) and [Linux](https://github.com/davidmoreno/rtpmidid). In theory, you spin up the RTP MIDI implementation of your choice and away you go.

But there will be bumps along the way if you intend on hosting your Internet-based MIDI host on a virtual machine. The first is that a sound card is required to make this work (more on this in a moment) - not an easy ask for a virtual machine. The second is that you'll need some sort of MIDI mixer/sequencer (that probably isn't the right term but go with me here) that allows you to connect MIDI sources and targets together. With a GUI there are a few options here ([Ableton](https://www.ableton.com/en/) is a good example for Mac) but your virtual machine may not have a GUI.

This (very tiny!) repo is here to help. Especially if you want to do this with Linux.

Linux can solve the first problem (virtual sound card) by supplying a "dummy" sound card, even in a virtual server environment. Without this, most applications that use the [Alsa](https://wiki.archlinux.org/title/Advanced_Linux_Sound_Architecture) libraries won't work. That includes anything that wants to use MIDI. Even if you have the Alsa tools and libraries installed, if there isn't a sound card present then everything just fails.

The second problem is solve using Alsa as well - there is a command-line tool called `aconnect` which allows you to join those MIDI sources and targets with each other.

In this repo is are two files:

 - midihub.pl - Python script that launches `rtpmidid` and when participants join each channel (identified by UDP ports) it automatically joins those participants with each other. This can listen on one or more ports (typically starting at port 5004 and going up in increments of two - it's a defacto thing in the RTP MIDI world).
 - midihub-cloudformation.yml - [AWS CloudFormation](https://aws.amazon.com/cloudformation/) template for building an appropriate Linux instance and deploying into AWS.

The intention is that you can run this solution when you need it and shut it down when you don't. To shut the solution down, you can go into the [EC2 console](https://ap-southeast-1.console.aws.amazon.com/ec2/), select the instance labelled `midiHub` then choose "Instance state" (top-right of the browser window) and click "Stop instance". You'll notice there is a "Start instance" choice there too - that's how you can restart the virtual machine running MidiHub.

If you choose "Terminate instance" then everything will be deleted - you'll have to deploy it again (see the instructions in the next section). Terminating the instance will mean that you are not paying anything while you are not using it. When it is in a "stopped" state you will be charge a little for the persitent storage - about US$0.10 (that's ten cents) per month.

EC2 instance pricing [can be found here](https://aws.amazon.com/ec2/pricing/on-demand/) - for most purposes the t3 instances will be fine - other instance types offer higher CPU speeds and better networking performance. MIDI is pretty low network usage so those should not be required.

## Deploy the CloudFormation template

To deploy in AWS, go to the [CloudFromation console](https://ap-southeast-1.console.aws.amazon.com/cloudformation/) and make sure you're deploying in the right AWS region. Typically you want to choose the region which is the lowest latency (over the internet) between all of the participants and that region. Then choose "Create stack" and when asked, upload the template file from this repo.

You'll be asked for the instance type 

The template assumes that your account has a default VPC which hasn't been modified - it will have a default public subnet with an Internet Gateway. Most accounts will have this (it is the default after all) but if you don't you'll need to modify the template to use a specific VPC.

The template creates an EC2 instance; EC2 instance profile; IAM role; Security Group and allocates an Elastic IP for the instance.

Deployment takes around ten minutes - there are a bunch of packages to install and the [rtpmidid]((https://github.com/davidmoreno/rtpmidid)) has to be compiled from source.

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

Install the Python `boto3` library (`sudo pip install boto3`) - this is used in AWS to determine which region the software is running in; outside of AWS it doesn't matter but it is included so installing boto3 will avoid any errors.

Download and build `rtpmidid` from https://github.com/davidmoreno/rtpmidid

Download `midihub.pl` and put it somewhere that you can run it. In AWS this is triggered every minute by cron - it automatically detects if it is still running and self-terminates if so. The running version starts `rtpmidid` and uses `aconnect` to join the MIDI sessions together. Options for where to find binaries are in `midihub.pl`.
