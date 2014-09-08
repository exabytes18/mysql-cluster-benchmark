#include <NdbApi.hpp>
#include <stdio.h>
#include <iostream>
#include <thread>

#define DATABASE_NAME "benchmarks"
#define TABLE_NAME "transactions"

#define PRINT_ERROR(code,msg) \
	std::cerr << "Error in " << __FILE__ << ", line: " << __LINE__ \
			  << ", code: " << code \
			  << ", msg: " << msg << "." << std::endl
#define APIERROR(error) { PRINT_ERROR(error.code, error.message); exit(-1); }
#define BLOCK_LOW(id,p,n) ((id)*(n)/(p))


static void insert(Ndb_cluster_connection* cluster_connection, int startAccountID, int endAccountID, int numTxnPerAccount, int numTxnPerBatch) {
	Ndb ndb(cluster_connection, DATABASE_NAME);
	if (ndb.init()) {
		APIERROR(ndb.getNdbError());
	}

	const NdbDictionary::Dictionary* dict = ndb.getDictionary();
	const NdbDictionary::Table* table = dict->getTable(TABLE_NAME);
	if (table == NULL) {
		APIERROR(dict->getNdbError());
	}

	int txnSize = 0;
	NdbTransaction* batch = NULL;
	for (int accountID = startAccountID; accountID < endAccountID; accountID++) {
		for (int txnID = 0; txnID < numTxnPerAccount; txnID++) {
			if (txnSize == numTxnPerBatch || batch == NULL) {
				if (batch != NULL) {
					if (batch->execute(NdbTransaction::Commit) == -1) {
						APIERROR(batch->getNdbError());
						return;
					}
					batch->close();
				} 
				
				txnSize = 0;
				batch = ndb.startTransaction();
				if (batch == NULL) {
					APIERROR(ndb.getNdbError());
					return;
				}
			}

			NdbOperation* op = batch->getNdbOperation(table);
			if (op == NULL) {
				APIERROR(batch->getNdbError());
				return;
			}
			
			op->insertTuple();
			op->equal("account_id", accountID);
			op->equal("txn_id", txnID);
			op->setValue("timestamp", rand());
			op->setValue("posted", rand() % 2 == 0);
			op->setValue("amount", 200 * (float)rand() / RAND_MAX);
			txnSize++;
		}
	}

	if (txnSize > 0) {
		if (batch->execute(NdbTransaction::Commit) == -1) {
			APIERROR(batch->getNdbError());
			return;
		}
		batch->close();
	}
}

static void run(const char* connectionString, int numAccounts, int numTxnPerAccount, int numThreads, int numTxnPerBatch) {
	Ndb_cluster_connection cluster_connection(connectionString);
	if (cluster_connection.connect(4, 5, 1)) {
		std::cerr << "Unable to connect to cluster management server" << std::endl;
		exit(1);
	}
	if (cluster_connection.wait_until_ready(30, 0) < 0) {
		std::cerr << "Unable to connect to datanodes" << std::endl;
		exit(1);
	}

	std::cout << "Connected to cluster; creating " << numThreads << " threads" << std::endl;
	std::thread* threads = new std::thread[numThreads];
	for (int thread = 0; thread < numThreads; thread++) {
		// Offset by 1 so accountIDs start at 1, rather than 0.
		int startAccountID = BLOCK_LOW(thread, numThreads, numAccounts) + 1;
		int endAccountID = BLOCK_LOW(thread + 1, numThreads, numAccounts) + 1;
		threads[thread] = std::thread(insert, &cluster_connection, startAccountID, endAccountID, numTxnPerAccount, numTxnPerBatch);
	}
	for (int thread = 0; thread < numThreads; thread++) {
		threads[thread].join();
	}
	delete[] threads;
}


int main(int argc, char** argv) {
	if (argc != 6) {
		std::cerr << "usage: " << argv[0] << " connectionString numAccounts numTxnPerAccount numThreads numTxnPerBatch" << std::endl;
		exit(1);
	}

	char* connectionString = argv[1];

	int numAccounts;
	try {
		numAccounts = std::stoi(argv[2]);
	} catch (std::invalid_argument e) {
		std::cerr << "Invalid numAccounts: '" << argv[2] << "'" << std::endl;
		exit(1);
	} catch (std::out_of_range e) {
		std::cerr << "Invalid numAccounts: '" << argv[2] << "'" << std::endl;
		exit(1);
	}
	if(numAccounts < 1) {
		std::cerr << "Invalid numAccounts: '" << argv[2] << "'; must be positive" << std::endl;
		exit(1);
	}

	int numTxnPerAccount;
	try {
		numTxnPerAccount = std::stoi(argv[3]);
	} catch(std::invalid_argument e) {
		std::cerr << "Invalid numTxnPerAccount: '" << argv[3] << "'" << std::endl;
		exit(1);
	} catch (std::out_of_range e) {
		std::cerr << "Invalid numTxnPerAccount: '" << argv[3] << "'" << std::endl;
		exit(1);
	}
	if(numTxnPerAccount < 1) {
		std::cerr << "Invalid numTxnPerAccount: '" << argv[3] << "'; must be positive" << std::endl;
		exit(1);
	}

	int numThreads;
	try {
		numThreads = std::stoi(argv[4]);
	} catch(std::invalid_argument e) {
		std::cerr << "Invalid numThreads: '" << argv[4] << "'" << std::endl;
		exit(1);
	} catch (std::out_of_range e) {
		std::cerr << "Invalid numThreads: '" << argv[4] << "'" << std::endl;
		exit(1);
	}
	if(numThreads < 1) {
		std::cerr << "Invalid numThreads: '" << argv[4] << "'; must be positive" << std::endl;
		exit(1);
	}

	int numTxnPerBatch;
	try {
		numTxnPerBatch = std::stoi(argv[5]);
	} catch(std::invalid_argument e) {
		std::cerr << "Invalid numTxnPerBatch: '" << argv[5] << "'" << std::endl;
		exit(1);
	} catch (std::out_of_range e) {
		std::cerr << "Invalid numTxnPerBatch: '" << argv[5] << "'" << std::endl;
		exit(1);
	}
	if(numTxnPerBatch < 1) {
		std::cerr << "Invalid numTxnPerBatch: '" << argv[5] << "'; must be positive" << std::endl;
		exit(1);
	}

	ndb_init();
	run(connectionString, numAccounts, numTxnPerAccount, numThreads, numTxnPerBatch);
	ndb_end(0);
	return 0;
}
