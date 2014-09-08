CC:=g++
OPTS:=-O3 -std=c++11
LIBS:=-lmysqlclient_r -lpthread -lm -ldl -lndbclient
INCLUDES:=-I/usr/include/mysql/storage/ndb/ndbapi -I/usr/include/mysql/storage/ndb

all: ndb-fetch ndb-load

.PHONY: clean

ndb-fetch: ndb-fetch.o
	$(CC) $(OPTS) $(LFLAGS) $(LIBS) $^ -o $@

ndb-load: ndb-load.o
	$(CC) $(OPTS) $(LFLAGS) $(LIBS) $^ -o $@

ndb-fetch.o: ndb-fetch.cpp
	$(CC) $(OPTS) $(INCLUDES) -c $^

ndb-load.o: ndb-load.cpp
	$(CC) $(OPTS) $(INCLUDES) -c $^

clean:
	rm -rf ndb-fetch ndb-fetch.o ndb-load ndb-load.o