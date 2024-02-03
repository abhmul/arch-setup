#!/bin/bash

# i3lock blurred screen inspired by /u/patopop007 and the blog post
# http://plankenau.com/blog/post-10/gaussianlock

# Timings are on an Intel i7-2630QM @ 2.00GHz

# Dependencies:
# imagemagick
# i3lock
# scrot (optional but default)

IMAGE=/tmp/i3lock.png
SCREENSHOT="scrot $IMAGE" # 0.46s

# Alternate screenshot method with imagemagick. NOTE: it is much slower
# SCREENSHOT="import -window root $IMAGE" # 1.35s

# Resize the image for increased speed
# Comment all for no scaling
#RESIZE="50%";UNRESIZE="200%"
RESIZE="25%";UNRESIZE="400%"
#RESIZE="5%"
#UNRESIZE="2000%"

# Here are some imagemagick blur types
# Uncomment one to use, if you have multiple, the last one will be used

# All options are here: http://www.imagemagick.org/Usage/blur/#blur_args
# Comment all for no blur
BLURTYPE="0x5" # 7.52s
#BLURTYPE="0x2" # 4.39s
#BLURTYPE="5x2" # 3.80s
#BLURTYPE="2x8" # 2.90s
#BLURTYPE="2x3" # 2.92s
#BLURTYPE="2x1"

# Get the screenshot, add the blur and lock the screen with it
$SCREENSHOT
convert $IMAGE -scale $RESIZE -blur $BLURTYPE -scale $UNRESIZE $IMAGE
i3lock -i $IMAGE
rm $IMAGE
