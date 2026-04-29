FROM public.ecr.aws/lambda/python:3.12

RUN microdnf install -y zip && microdnf clean all

WORKDIR /build/value_analysis
RUN mkdir -p /artifacts

COPY src/lambda/value_analysis/requirements.txt /tmp/requirements.txt
RUN python -m pip install --upgrade pip && pip install -r /tmp/requirements.txt -t .

COPY src/lambda/value_analysis/lambda_function.py ./

RUN zip -r9 /artifacts/value_analysis.zip .