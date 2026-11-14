## What I did
- I built an image pipeline that crops each frame, corrects the white balance and masks the soil, extracting the leaves above it.
- I trained a colour model for each plant in leaf_finder: it publishes the leaf position as a topic named leaf_<id>.
- My planner reads that topic and drives the gantry with ros2_control, using a Cartesian solver for the 3-axis gantry.
- I'm a robotics builder, so I leveraged a robust Kalman filter to smooth the readings.
