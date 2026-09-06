#!/usr/bin/env python3
import os
import aws_cdk as cdk
from strava_stack.stack import StravaStack

app = cdk.App()
StravaStack(app, "StravaGhostwriterStack",
    env=cdk.Environment(
        account=os.getenv('CDK_DEFAULT_ACCOUNT'),
        region=os.getenv('CDK_DEFAULT_REGION')
    ),
)
app.synth()
