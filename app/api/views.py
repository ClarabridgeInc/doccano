import logging
import requests
import time
import json
from . import export_annotations
from os import path
from django.conf import settings
from django.contrib.auth.models import User
from django.shortcuts import get_object_or_404, redirect
from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import Count, F
from libcloud.base import DriverType, get_driver
from libcloud.storage.types import ContainerDoesNotExistError, ObjectDoesNotExistError
from rest_framework import generics, filters, status
from rest_framework.exceptions import ParseError, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.parsers import MultiPartParser
from rest_framework_csv.renderers import CSVRenderer

from .filters import DocumentFilter
from .models import Project, Label, Document, RoleMapping, Role
from .permissions import IsProjectAdmin, IsAnnotatorAndReadOnly, IsAnnotator, IsAnnotationApproverAndReadOnly, IsOwnAnnotation, IsAnnotationApprover
from .serializers import ProjectSerializer, LabelSerializer, DocumentSerializer, UserSerializer
from .serializers import ProjectPolymorphicSerializer, RoleMappingSerializer, RoleSerializer
from .utils import CSVParser, ExcelParser, JSONParser, RawTextParser, RawJSONParser, PlainTextParser, CoNLLParser, iterable_to_io
from .utils import JSONLRenderer
from .utils import JSONPainter, CSVPainter
IsInProjectReadOnlyOrAdmin = (IsAnnotatorAndReadOnly | IsAnnotationApproverAndReadOnly | IsProjectAdmin)
IsInProjectOrAdmin = (IsAnnotator | IsAnnotationApprover | IsProjectAdmin)

logger = logging.getLogger(__name__)


class Me(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request, *args, **kwargs):
        serializer = UserSerializer(request.user, context={'request': request})
        return Response(serializer.data)


class Features(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request, *args, **kwargs):
        return Response({
            'cloud_upload': bool(settings.CLOUD_BROWSER_APACHE_LIBCLOUD_PROVIDER),
        })


class ProjectList(generics.ListCreateAPIView):
    serializer_class = ProjectPolymorphicSerializer
    pagination_class = None
    permission_classes = [IsAuthenticated & IsInProjectReadOnlyOrAdmin]

    def get_queryset(self):
        return self.request.user.projects

    def perform_create(self, serializer):
        serializer.save(users=[self.request.user])


class ProjectDetail(generics.RetrieveUpdateDestroyAPIView):
    queryset = Project.objects.all()
    serializer_class = ProjectSerializer
    lookup_url_kwarg = 'project_id'
    permission_classes = [IsAuthenticated & IsInProjectReadOnlyOrAdmin]


class StatisticsAPI(APIView):
    pagination_class = None
    permission_classes = [IsAuthenticated & IsInProjectReadOnlyOrAdmin]

    def get(self, request, *args, **kwargs):
        p = get_object_or_404(Project, pk=self.kwargs['project_id'])
        label_count, user_count = self.label_per_data(p)
        progress = self.progress(project=p)
        response = dict()
        response['label'] = label_count
        response['user'] = user_count
        response.update(progress)
        return Response(response)

    def progress(self, project):
        docs = project.documents
        annotation_class = project.get_annotation_class()
        total = docs.count()
        done = annotation_class.objects.filter(document_id__in=docs.all(),
            user_id=self.request.user).\
            aggregate(Count('document', distinct=True))['document__count']
        remaining = total - done
        return {'total': total, 'remaining': remaining}

    def label_per_data(self, project):
        annotation_class = project.get_annotation_class()
        return annotation_class.objects.get_label_per_data(project=project)


class ApproveLabelsAPI(APIView):
    permission_classes = [IsAuthenticated & (IsAnnotationApprover | IsProjectAdmin)]

    def post(self, request, *args, **kwargs):
        approved = self.request.data.get('approved', True)
        document = get_object_or_404(Document, pk=self.kwargs['doc_id'])
        document.annotations_approved_by = self.request.user if approved else None
        document.save()
        return Response(DocumentSerializer(document).data)


class LabelList(generics.ListCreateAPIView):
    serializer_class = LabelSerializer
    pagination_class = None
    permission_classes = [IsAuthenticated & IsInProjectReadOnlyOrAdmin]

    def get_queryset(self):
        project = get_object_or_404(Project, pk=self.kwargs['project_id'])
        return project.labels.order_by('text')

    def perform_create(self, serializer):
        project = get_object_or_404(Project, pk=self.kwargs['project_id'])
        serializer.save(project=project)


class LabelDetail(generics.RetrieveUpdateDestroyAPIView):
    queryset = Label.objects.all()
    serializer_class = LabelSerializer
    lookup_url_kwarg = 'label_id'
    permission_classes = [IsAuthenticated & IsInProjectReadOnlyOrAdmin]


class DocumentList(generics.ListCreateAPIView):
    serializer_class = DocumentSerializer
    filter_backends = (DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter)
    search_fields = ('text', )
    ordering_fields = ('created_at', 'updated_at', 'doc_annotations__updated_at',
                       'seq_annotations__updated_at', 'seq2seq_annotations__updated_at')
    filter_class = DocumentFilter
    permission_classes = [IsAuthenticated & IsInProjectReadOnlyOrAdmin]

    def get_queryset(self):
        project = get_object_or_404(Project, pk=self.kwargs['project_id'])

        queryset = project.documents
        if project.randomize_document_order:
            queryset = queryset.annotate(sort_id=F('id') % self.request.user.id).order_by('sort_id')

        return queryset

    def perform_create(self, serializer):
        project = get_object_or_404(Project, pk=self.kwargs['project_id'])
        serializer.save(project=project)


class DocumentDetail(generics.RetrieveUpdateDestroyAPIView):
    queryset = Document.objects.all()
    serializer_class = DocumentSerializer
    lookup_url_kwarg = 'doc_id'
    permission_classes = [IsAuthenticated & IsInProjectReadOnlyOrAdmin]


class AnnotationList(generics.ListCreateAPIView):
    pagination_class = None
    permission_classes = [IsAuthenticated & IsInProjectOrAdmin]

    def get_serializer_class(self):
        project = get_object_or_404(Project, pk=self.kwargs['project_id'])
        self.serializer_class = project.get_annotation_serializer()
        return self.serializer_class

    def get_queryset(self):
        project = get_object_or_404(Project, pk=self.kwargs['project_id'])
        model = project.get_annotation_class()

        queryset = model.objects.filter(document=self.kwargs['doc_id'])
        if not project.collaborative_annotation:
            queryset = queryset.filter(user=self.request.user)

        return queryset

    def create(self, request, *args, **kwargs):
        request.data['document'] = self.kwargs['doc_id']
        return super().create(request, args, kwargs)

    def perform_create(self, serializer):
        doc = get_object_or_404(Document, pk=self.kwargs['doc_id'])
        serializer.save(document=doc, user=self.request.user)


class AnnotationDetail(generics.RetrieveUpdateDestroyAPIView):
    lookup_url_kwarg = 'annotation_id'
    permission_classes = [IsAuthenticated & (((IsAnnotator | IsAnnotationApprover) & IsOwnAnnotation) | IsProjectAdmin)]

    def get_serializer_class(self):
        project = get_object_or_404(Project, pk=self.kwargs['project_id'])
        self.serializer_class = project.get_annotation_serializer()
        return self.serializer_class

    def get_queryset(self):
        project = get_object_or_404(Project, pk=self.kwargs['project_id'])
        model = project.get_annotation_class()
        self.queryset = model.objects.all()
        return self.queryset


class TextUploadAPI(APIView):
    parser_classes = (MultiPartParser,)
    permission_classes = [IsAuthenticated & IsProjectAdmin]

    def post(self, request, *args, **kwargs):
        if 'file' not in request.data:
            raise ParseError('Empty content')

        self.save_file(
            user=request.user,
            file=request.data['file'],
            file_format=request.data['format'],
            project_id=kwargs['project_id'],
        )

        return Response(status=status.HTTP_201_CREATED)

    @classmethod
    def save_file(cls, user, file, file_format, project_id):
        project = get_object_or_404(Project, pk=project_id)
        parser = cls.select_parser(file_format)
        data = parser.parse(file)
        storage = project.get_storage(data)
        storage.save(user)

    @classmethod
    def select_parser(cls, file_format):
        if file_format == 'plain':
            return PlainTextParser()
        elif file_format == 'raw_text':
            return RawTextParser()
        elif file_format == 'raw_json':
            return RawJSONParser()
        elif file_format == 'csv':
            return CSVParser()
        elif file_format == 'json':
            return JSONParser()
        elif file_format == 'conll':
            return CoNLLParser()
        elif file_format == 'excel':
            return ExcelParser()
        else:
            raise ValidationError('format {} is invalid.'.format(file_format))


class FileServerUpload(APIView):
    permission_classes = TextUploadAPI.permission_classes

    def get(self, request, *args, **kwargs):

        try:
            member = request.query_params['member']
            if member == "BCBS":
                base_url = "https://10.188.101.153:8443/vocioutput/acq_connector/blond01.clarabridge.net/16394744/"
            elif member == "FB":
                base_url = "https://10.188.101.153:8443/vocioutput/acq_connector/10.80.253.172/100049/"
            else:
                raise ValidationError('query parameter member value is not supported')
        except KeyError as ex:
            try:
                base_url = request.query_params['base_url']
            except KeyError as ex:
                raise ValidationError('was not able to dervive base_url from base_url or member query parameter')
            except MultiValueDictKeyError as ex:
                raise ValidationError('was not able to dervive base_url from base_url or member query parameter')

        try:
            project_id = request.query_params['project_id']
            file_name = request.query_params['file_name']
            with open(path.join(settings.CONVERSATION_ROOT, file_name)) as f:
                file_list = f.readlines()
        except KeyError as ex:
            raise ValidationError('query parameter {} is missing'.format(ex))
        except FileNotFoundError:
            raise ValidationError('file {} does not exist'.format(file_name))

        for file_name in file_list:
            try:
                single_file = requests.get((base_url+file_name).strip(),
                                           auth=(settings.FILE_SERVICE_USERNAME,
                                                 settings.FILE_SERVICE_PASSWORD), verify=False).text
            except Exception as e:
                raise ParseError("couldn't retrieve {} from file server".format(base_url+file_name))
            
            try:
                TextUploadAPI.save_file(
                    user=request.user,
                    file={"text": single_file, "meta": {"filename": file_name,
                                                        "file_no_ext": file_name.replace('.txt','')} },
                    file_format="raw_json",
                    project_id=project_id,
                )
            except Exception as e:
                print(f"Failed uploading {file_name}")

        return Response(status=status.HTTP_201_CREATED)


class CloudUploadAPI(APIView):
    permission_classes = TextUploadAPI.permission_classes

    def get(self, request, *args, **kwargs):
        try:
            project_id = request.query_params['project_id']
            file_format = request.query_params['upload_format']
            cloud_container = request.query_params['container']
            cloud_object = request.query_params['object']
        except KeyError as ex:
            raise ValidationError('query parameter {} is missing'.format(ex))

        try:
            cloud_file = self.get_cloud_object_as_io(cloud_container, cloud_object)
        except ContainerDoesNotExistError:
            raise ValidationError('cloud container {} does not exist'.format(cloud_container))
        except ObjectDoesNotExistError:
            raise ValidationError('cloud object {} does not exist'.format(cloud_object))

        TextUploadAPI.save_file(
            user=request.user,
            file=cloud_file,
            file_format=file_format,
            project_id=project_id,
        )

        next_url = request.query_params.get('next')

        if next_url == 'about:blank':
            return Response(data='', content_type='text/plain', status=status.HTTP_201_CREATED)

        if next_url:
            return redirect(next_url)

        return Response(status=status.HTTP_201_CREATED)

    @classmethod
    def get_cloud_object_as_io(cls, container_name, object_name):
        provider = settings.CLOUD_BROWSER_APACHE_LIBCLOUD_PROVIDER.lower()
        account = settings.CLOUD_BROWSER_APACHE_LIBCLOUD_ACCOUNT
        key = settings.CLOUD_BROWSER_APACHE_LIBCLOUD_SECRET_KEY

        driver = get_driver(DriverType.STORAGE, provider)
        client = driver(account, key)

        cloud_container = client.get_container(container_name)
        cloud_object = cloud_container.get_object(object_name)

        return iterable_to_io(cloud_object.as_stream())


class TextDownloadAPI(APIView):
    permission_classes = TextUploadAPI.permission_classes

    renderer_classes = (CSVRenderer, JSONLRenderer)

    def get(self, request, *args, **kwargs):
        format = request.query_params.get('q')
        project = get_object_or_404(Project, pk=self.kwargs['project_id'])
        documents = project.documents.all()
        painter = self.select_painter(format)
        # json1 format prints text labels while json format prints annotations with label ids
        # json1 format - "labels": [[0, 15, "PERSON"], ..]
        # json format - "annotations": [{"label": 5, "start_offset": 0, "end_offset": 2, "user": 1},..]
        labels = project.labels.all()
        serializer_labels = LabelSerializer(labels, many=True)
        labbel_mapper = {}
        for x in serializer_labels.data:
            labbel_mapper[x['id']] = x['text'] 
        if format == "json1":
            data = JSONPainter.paint_labels(documents, labels)
        else:
            data = painter.paint(documents)

        exp_file_name = f"project_{self.kwargs['project_id']}_name_{project.name}_time_{str(int(time.time() * 1000000))}.exported"
        with open(path.join(settings.ANNOTATION_ROOT, exp_file_name), "w") as f:
            f.write(json.dumps(data))
        export_annotations.export_post_process(labbel_mapper, data,  project.name, self.kwargs['project_id'], str(int(time.time() * 1000000)))
                
        return Response(None)

    def select_painter(self, format):
        if format == 'csv':
            return CSVPainter()
        elif format == 'json' or format == "json1":
            return JSONPainter()
        else:
            raise ValidationError('format {} is invalid.'.format(format))


class Users(APIView):
    permission_classes = [IsAuthenticated & IsProjectAdmin]

    def get(self, request, *args, **kwargs):
        queryset = User.objects.all()
        serialized_data = UserSerializer(queryset, many=True).data
        return Response(serialized_data)


class Roles(generics.ListCreateAPIView):
    serializer_class = RoleSerializer
    pagination_class = None
    permission_classes = [IsAuthenticated & IsProjectAdmin]
    queryset = Role.objects.all()


class RoleMappingList(generics.ListCreateAPIView):
    serializer_class = RoleMappingSerializer
    pagination_class = None
    permission_classes = [IsAuthenticated & IsProjectAdmin]

    def get_queryset(self):
        project = get_object_or_404(Project, pk=self.kwargs['project_id'])
        return project.role_mappings

    def perform_create(self, serializer):
        project = get_object_or_404(Project, pk=self.kwargs['project_id'])
        serializer.save(project=project)


class RoleMappingDetail(generics.RetrieveUpdateDestroyAPIView):
    queryset = RoleMapping.objects.all()
    serializer_class = RoleMappingSerializer
    lookup_url_kwarg = 'rolemapping_id'
    permission_classes = [IsAuthenticated & IsProjectAdmin]
