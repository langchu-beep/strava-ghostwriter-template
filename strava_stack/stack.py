from aws_cdk import (
    Stack,
    Duration,
    RemovalPolicy,
    aws_lambda as _lambda,
    aws_iam as iam,
    aws_apigateway as apigw,
    aws_sqs as sqs,
    aws_lambda_event_sources as lambda_events,
    aws_s3 as s3,
    aws_events as events,
    aws_events_targets as targets,
    aws_secretsmanager as secretsmanager,
    aws_bedrock as bedrock,
    aws_ses as ses,
    aws_ses_actions as ses_actions,
    aws_route53 as route53,
    aws_s3_notifications as s3n,
)
from constructs import Construct

class StravaStack(Stack):
    def __init__(self, scope: Construct, id: str, **kwargs):
        super().__init__(scope, id, **kwargs)

        # 1. S3 Bucket for Strava History (Knowledge Base source)
        history_bucket = s3.Bucket(
            self, "StravaHistoryBucket",
            removal_policy=RemovalPolicy.RETAIN,
            versioned=True,
        )

        # 2. SQS Queue for Webhook processing
        webhook_queue = sqs.Queue(
            self, "StravaWebhookQueue",
            visibility_timeout=Duration.seconds(300),
            retention_period=Duration.days(1)
        )

        # 3. API Gateway -> SQS Integration
        api = apigw.RestApi(self, "StravaWebhookApi", rest_api_name="Strava Webhook API")
        
        apigw_sqs_role = iam.Role(
            self, "ApiGatewaySqsRole",
            assumed_by=iam.ServicePrincipal("apigateway.amazonaws.com")
        )
        webhook_queue.grant_send_messages(apigw_sqs_role)

        sqs_integration = apigw.AwsIntegration(
            service="sqs",
            integration_http_method="POST",
            path=f"{self.account}/{webhook_queue.queue_name}",
            options=apigw.IntegrationOptions(
                credentials_role=apigw_sqs_role,
                request_parameters={
                    "integration.request.header.Content-Type": "'application/x-www-form-urlencoded'"
                },
                request_templates={
                    "application/json": "Action=SendMessage&MessageBody=$util.urlEncode($input.body)"
                },
                integration_responses=[
                    apigw.IntegrationResponse(status_code="200", response_templates={"application/json": '{"status": "ok"}'})
                ]
            )
        )

        api.root.add_method(
            "POST", sqs_integration,
            method_responses=[apigw.MethodResponse(status_code="200")]
        )
        
        api.root.add_method(
            "GET", apigw.MockIntegration(
                integration_responses=[
                    apigw.IntegrationResponse(
                        status_code="200",
                        response_templates={
                            "application/json": """
                                #set($challenge = $input.params('hub.challenge'))
                                {
                                  "hub.challenge": "$challenge"
                                }
                            """
                        }
                    )
                ],
                request_templates={"application/json": '{"statusCode": 200}'}
            ),
            method_responses=[apigw.MethodResponse(status_code="200")]
        )

        # 4. Secrets Manager Reference
        jarvis_secrets = secretsmanager.Secret.from_secret_name_v2(
            self, "JarvisSecrets", "StravaJarvisSecrets"
        )

        # 4.5. Bedrock Knowledge Base (Pinecone)
        # Create Knowledge Base execution role with INLINE policies to prevent CFN race conditions
        kb_role = iam.Role(
            self, "KnowledgeBaseRole",
            assumed_by=iam.ServicePrincipal("bedrock.amazonaws.com"),
            inline_policies={
                "KBPolicy": iam.PolicyDocument(
                    statements=[
                        iam.PolicyStatement(
                            actions=["bedrock:InvokeModel"],
                            resources=["arn:aws:bedrock:us-east-1::foundation-model/amazon.titan-embed-text-v1"]
                        ),
                        iam.PolicyStatement(
                            actions=["secretsmanager:GetSecretValue"],
                            resources=["arn:aws:secretsmanager:us-east-1:235970410053:secret:PineconeAPIKey-osO3q5"]
                        ),
                        iam.PolicyStatement(
                            actions=["s3:ListBucket", "s3:GetObject"],
                            resources=[
                                history_bucket.bucket_arn,
                                f"{history_bucket.bucket_arn}/*"
                            ]
                        )
                    ]
                )
            }
        )

        knowledge_base = bedrock.CfnKnowledgeBase(
            self, "StravaKnowledgeBase",
            name="strava-knowledge-base",
            role_arn=kb_role.role_arn,
            knowledge_base_configuration=bedrock.CfnKnowledgeBase.KnowledgeBaseConfigurationProperty(
                type="VECTOR",
                vector_knowledge_base_configuration=bedrock.CfnKnowledgeBase.VectorKnowledgeBaseConfigurationProperty(
                    embedding_model_arn="arn:aws:bedrock:us-east-1::foundation-model/amazon.titan-embed-text-v1"
                )
            ),
            storage_configuration=bedrock.CfnKnowledgeBase.StorageConfigurationProperty(
                type="PINECONE",
                pinecone_configuration=bedrock.CfnKnowledgeBase.PineconeConfigurationProperty(
                    connection_string="https://strava-kb-n4joefe.svc.aped-4627-b74a.pinecone.io",
                    credentials_secret_arn="arn:aws:secretsmanager:us-east-1:235970410053:secret:PineconeAPIKey-osO3q5",
                    field_mapping=bedrock.CfnKnowledgeBase.PineconeFieldMappingProperty(
                        metadata_field="metadata",
                        text_field="text"
                    )
                )
            )
        )

        data_source_activities = bedrock.CfnDataSource(
            self, "StravaDataSourceActivities",
            name="strava-data-source-activities",
            knowledge_base_id=knowledge_base.attr_knowledge_base_id,
            data_source_configuration=bedrock.CfnDataSource.DataSourceConfigurationProperty(
                type="S3",
                s3_configuration=bedrock.CfnDataSource.S3DataSourceConfigurationProperty(
                    bucket_arn=history_bucket.bucket_arn,
                    inclusion_prefixes=["activities/"]
                )
            )
        )
        
        data_source_memory = bedrock.CfnDataSource(
            self, "StravaDataSourceMemory",
            name="strava-data-source-memory",
            knowledge_base_id=knowledge_base.attr_knowledge_base_id,
            data_source_configuration=bedrock.CfnDataSource.DataSourceConfigurationProperty(
                type="S3",
                s3_configuration=bedrock.CfnDataSource.S3DataSourceConfigurationProperty(
                    bucket_arn=history_bucket.bucket_arn,
                    inclusion_prefixes=["memory/"]
                )
            )
        )

        # 5. Analysis Lambda
        analysis_fn = _lambda.Function(
            self, "AnalysisWorkerFn",
            runtime=_lambda.Runtime.PYTHON_3_11,
            handler="lambda_function.analysis_handler",
            code=_lambda.Code.from_asset("lambda"),
            timeout=Duration.seconds(300),
            environment={
                "SECRET_ID": jarvis_secrets.secret_name,
                "HISTORY_BUCKET": history_bucket.bucket_name,
                "USER_EMAIL": "ashish.mainali@icloud.com",
                "KNOWLEDGE_BASE_ID": knowledge_base.attr_knowledge_base_id,
                "DATA_SOURCE_ACTIVITIES_ID": data_source_activities.attr_data_source_id,
            },
        )
        jarvis_secrets.grant_read(analysis_fn)
        history_bucket.grant_read_write(analysis_fn)
        analysis_fn.add_event_source(lambda_events.SqsEventSource(webhook_queue, batch_size=1))
        
        analysis_fn.add_to_role_policy(iam.PolicyStatement(
            actions=["bedrock:InvokeModel", "bedrock:InvokeAgent", "ses:SendEmail", "bedrock:RetrieveAndGenerate", "bedrock:Retrieve", "bedrock:StartIngestionJob"],
            resources=["*"]
        ))

        # 6. Weekly Summary Cron Lambda
        summary_fn = _lambda.Function(
            self, "WeeklySummaryFn",
            runtime=_lambda.Runtime.PYTHON_3_11,
            handler="lambda_function.summary_handler",
            code=_lambda.Code.from_asset("lambda"),
            timeout=Duration.seconds(300),
            environment={
                "SECRET_ID": jarvis_secrets.secret_name,
                "USER_EMAIL": "ashish.mainali@icloud.com",
            },
        )
        jarvis_secrets.grant_read(summary_fn)
        summary_fn.add_to_role_policy(iam.PolicyStatement(
            actions=["bedrock:InvokeModel", "bedrock:InvokeAgent", "ses:SendEmail"],
            resources=["*"]
        ))

        events.Rule(
            self, "WeeklySummaryRule",
            schedule=events.Schedule.cron(minute="0", hour="22", week_day="SUN"),
            targets=[targets.LambdaFunction(summary_fn)]
        )

                # 7. SES Inbound Routing for lightworkrunclub.com
        hosted_zone = route53.HostedZone.from_lookup(self, "LightworkZone", domain_name="lightworkrunclub.com")
        
        # Verify domain in SES (CDK will create the necessary DNS TXT records)
        ses_identity = ses.EmailIdentity(self, "LightworkIdentity",
            identity=ses.Identity.domain("lightworkrunclub.com")
        )
        
        # Add MX Record for inbound emails
        route53.MxRecord(self, "InboundMX",
            zone=hosted_zone,
            values=[route53.MxRecordValue(
                host_name="inbound-smtp.us-east-1.amazonaws.com",
                priority=10
            )]
        )
        
        # SES Receipt Rule to save raw emails to S3 bucket
        rule_set = ses.ReceiptRuleSet(self, "RuleSet")
        rule_set.add_rule("JarvisInboundRule",
            recipients=["jarvis@lightworkrunclub.com"],
            actions=[
                ses_actions.S3(
                    bucket=history_bucket,
                    object_key_prefix="inbox/"
                )
            ]
        )

        # 8. Inbound Email Lambda (triggered by S3)
        inbound_fn = _lambda.Function(
            self, "InboundEmailFn",
            runtime=_lambda.Runtime.PYTHON_3_11,
            handler="lambda_function.inbound_handler",
            code=_lambda.Code.from_asset("lambda"),
            timeout=Duration.seconds(300),
            environment={
                "SECRET_ID": jarvis_secrets.secret_name,
                "HISTORY_BUCKET": history_bucket.bucket_name,
                "KNOWLEDGE_BASE_ID": knowledge_base.attr_knowledge_base_id,
                "DATA_SOURCE_MEMORY_ID": data_source_memory.attr_data_source_id,
            },
        )
        jarvis_secrets.grant_read(inbound_fn)
        history_bucket.grant_read_write(inbound_fn)
        inbound_fn.add_to_role_policy(iam.PolicyStatement(
            actions=["bedrock:InvokeAgent", "bedrock:StartIngestionJob"],
            resources=["*"]
        ))
        
        # Trigger inbound_fn when new raw email lands in inbox/
        history_bucket.add_event_notification(
            s3.EventType.OBJECT_CREATED,
            s3n.LambdaDestination(inbound_fn),
            s3.NotificationKeyFilter(prefix="inbox/")
        )

        # 9. Garmin Sync Lambda and Layer
        garmin_layer = _lambda.LayerVersion(
            self, "GarminLayer",
            code=_lambda.Code.from_asset("lambda/layer"),
            compatible_runtimes=[_lambda.Runtime.PYTHON_3_11],
            description="GarminConnect Python Library"
        )
        
        garmin_fn = _lambda.Function(
            self, "GarminSyncFn",
            runtime=_lambda.Runtime.PYTHON_3_11,
            handler="garmin_sync.handler",
            code=_lambda.Code.from_asset("lambda"),
            timeout=Duration.seconds(300),
            layers=[garmin_layer],
            environment={
                "SECRET_ID": jarvis_secrets.secret_name,
                "HISTORY_BUCKET": history_bucket.bucket_name,
                "KNOWLEDGE_BASE_ID": knowledge_base.attr_knowledge_base_id,
                "DATA_SOURCE_MEMORY_ID": data_source_memory.attr_data_source_id,
            },
        )
        jarvis_secrets.grant_read(garmin_fn)
        history_bucket.grant_read_write(garmin_fn)
        garmin_fn.add_to_role_policy(iam.PolicyStatement(
            actions=["bedrock:StartIngestionJob"],
            resources=["*"]
        ))
        
        # Schedule Garmin sync every morning at 13:00 UTC (8:00 AM CST)
        events.Rule(
            self, "GarminSyncRule",
            schedule=events.Schedule.cron(minute="0", hour="13"),
            targets=[targets.LambdaFunction(garmin_fn)]
        )
        
        # --- Engagement Feedback Loop Lambda ---
        engagement_fn = _lambda.Function(
            self, "EngagementSyncFn",
            runtime=_lambda.Runtime.PYTHON_3_11,
            handler="engagement_sync.handler",
            code=_lambda.Code.from_asset("lambda"),
            timeout=Duration.seconds(300),
            environment={
                "SECRET_ID": jarvis_secrets.secret_name,
                "HISTORY_BUCKET": history_bucket.bucket_name,
                "KNOWLEDGE_BASE_ID": knowledge_base.attr_knowledge_base_id,
                "DATA_SOURCE_MEMORY_ID": data_source_memory.attr_data_source_id,
            },
        )
        jarvis_secrets.grant_read(engagement_fn)
        history_bucket.grant_read_write(engagement_fn)
        engagement_fn.add_to_role_policy(iam.PolicyStatement(
            actions=["bedrock:StartIngestionJob"],
            resources=["*"]
        ))
        
        # Schedule Engagement Sync every Sunday at 20:00 UTC (3:00 PM CST)
        events.Rule(
            self, "EngagementSyncRule",
            schedule=events.Schedule.cron(minute="0", hour="20", week_day="SUN"),
            targets=[targets.LambdaFunction(engagement_fn)]
        )

