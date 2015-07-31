# -*- coding: utf-8 -*-
import traceback
import functools
from django.db import connection
from django.contrib.auth.models import User, Group
from django.forms.models import model_to_dict
from django.core.exceptions import *
from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.decorators import detail_route
from rest_framework import exceptions
from rest_framework import status

from models import InterfaceEntry
from serializers import UserSerializer, GroupSerializer
from serializers import InterfaceEntrySerializer
from serializers import convert_to_serializer
from inspect import convert_to_model


def request_content_error_handler(func):
    @functools.wraps(func)
    def deco(*args, **kwargs):
        try:
            request = args[1]
            if not request.data:
                assert False, 'No json be encoded'

            assert isinstance(request.data, dict), 'expected string or buffer'
            return func(*args, **kwargs)
        except AssertionError as e:
            raise exceptions.ParseError(e.args[0])
    return deco


class UserViewSet(viewsets.ModelViewSet):
    """
    API endpoint that allows users to be viewed or edited.
    """
    queryset = User.objects.all()
    serializer_class = UserSerializer


class GroupViewSet(viewsets.ModelViewSet):
    """
    API endpoint that allows groups to be viewed or edited.
    """
    queryset = Group.objects.all()
    serializer_class = GroupSerializer


class InterfaceListCreateViewSet(viewsets.ModelViewSet):
    """
    数据表创建以及查看数据表数据，和推送数据表数据.
    """
    permission_classes = (IsAuthenticated,)
    queryset = InterfaceEntry.objects.all()
    serializer_class = InterfaceEntrySerializer

    def sql_validate(self, sql):
        action, object = sql.split(' ')[0:2]
        if 'CREATE' == action.upper() and 'TABLE' == object.upper():
            return True
        return False
    
    def create_table(self, sql):
        try:
            cursor = connection.cursor()
            result = cursor.execute(sql)
            if 'primary key' not in sql.lower():
                table_name = self.parse_sql_table_name(sql)
                sql = "ALTER TABLE %s ADD id int(11) AUTO_INCREMENT PRIMARY KEY;"\
                        % table_name
                result = cursor.execute(sql)
        except Exception as e:
            raise exceptions.APIException("Create table error. E:%s" % str(e))
        return True

    def parse_sql_table_name(self, sql):
        # Get table name in sql and remote '`'
        table_name = sql.split(' ')[2]
        table_name = table_name.replace('`', '')
        return table_name

    @request_content_error_handler
    def create(self, request):
        """可以通过此接口创建一张数据表, 只需要在POST需要时定义`sql`键值."""
        user = User.objects.filter(username=request.user)[0]

        # Request validate
        try:
            sql = request.DATA.get('sql', None)
            if sql is None:
                raise exceptions.ParseError("Sql not privote")
        except:
            raise exceptions.ParseError("Sql not privote")

        table_name = self.parse_sql_table_name(sql)
        if not self.sql_validate(sql):
            raise exceptions.ParseError("Sql not a create table sql")
        
        # Save the object
        data = { "owner": user.id, "sql": sql, "tname": table_name }
        serializer = self.get_serializer(data=data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)

        # Create table using request sql
        self.create_table(sql) 

        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)

    def validate_model(self, request, table_name):
        table_entrys = InterfaceEntry.objects.filter(tname=table_name)
        user = User.objects.filter(username=request.user)[0]

        # Get a table entry
        if table_entrys and len(table_entrys) == 1:
            table_entry = table_entrys[0]
        else:
            raise exceptions.APIException(u"关系表异常 E: %s" % locals)

        # Permission validate
        if table_entry.owner_id <> int(user.id):
            raise exceptions.PermissionDenied

        try:
            model = convert_to_model(table_name)
            return model
        except Exception as e:
            raise exceptions.APIException("Convert to model error. E:%s" % str(e))

    @request_content_error_handler
    def push(self, request, pk, format=None):
        """可以通过此接口推送数据到一张表, 需要定义数据字段和对应值."""
        try:
            model = self.validate_model(request, str(pk))
            serializer_class = convert_to_serializer(str(pk + 'serializer'), model)
            setattr(self, 'serializer_class', serializer_class)

            serializer = self.get_serializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            self.perform_create(serializer)
            headers = self.get_success_headers(serializer.data)
            return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)
        except ValidationError as e:
            raise exceptions.APIException("ValidationError E:%s" % str(e))
        except TypeError as e:
            raise exceptions.APIException("TypeError E:%s" % str(e))

    def pull(self, request, pk):
        """可以通过此接口查看一张表数据, 注意由于数据不固定，目前仅提供100条."""
        model = self.validate_model(request, str(pk))
        serializer_class = convert_to_serializer(str(pk + 'serializer'), model)

        setattr(self, 'serializer_class', serializer_class)
        setattr(self, 'queryset', model.objects.all())

        queryset = self.filter_queryset(self.get_queryset())

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    @detail_route()
    def attribute(self, request, pk):
        try:
            model = self.validate_model(request, str(pk))
            entrys = model.objects.all()[0:100]
        except Exception as e:
            print traceback.format_exc()            
            raise exceptions.APIException("Convert to model error. E:%s" % str(e))


