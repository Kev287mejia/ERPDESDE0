from decimal import Decimal
from django.db.models import Sum
from django.utils import timezone

from apps.finance.models import AccountingAccount, JournalEntry, JournalEntryLine


class FinancialStatementsService:
    """
    Motor de Estados Financieros en Tiempo Real para el ERP.
    Opera sobre la estructura contable de partida doble (AccountingAccount, JournalEntry, JournalEntryLine)
    estrictamente aislado por Organización.
    """

    @classmethod
    def get_trial_balance(cls, organization, date_from=None, date_to=None):
        """
        Genera la Balanza de Comprobación de sumas y saldos.
        Agrupa los movimientos del Debe y Haber por cuenta contable y determina
        el saldo neto deudor o acreedor según la naturaleza de la cuenta.
        """
        lines_qs = JournalEntryLine.objects.filter(
            entry__organization=organization,
        )

        if date_from:
            lines_qs = lines_qs.filter(entry__date__gte=date_from)
        if date_to:
            lines_qs = lines_qs.filter(entry__date__lte=date_to)

        grouped = lines_qs.values(
            'account__id',
            'account__code',
            'account__name',
            'account__account_type',
        ).annotate(
            total_debit=Sum('debit'),
            total_credit=Sum('credit'),
        ).order_by('account__code')

        accounts = []
        sum_debits = Decimal('0.00')
        sum_credits = Decimal('0.00')
        sum_debit_balance = Decimal('0.00')
        sum_credit_balance = Decimal('0.00')

        for row in grouped:
            code = row['account__code']
            name = row['account__name']
            account_type = row['account__account_type']
            debit = Decimal(str(row['total_debit'] or '0.00'))
            credit = Decimal(str(row['total_credit'] or '0.00'))

            sum_debits += debit
            sum_credits += credit

            # Naturaleza Deudora: Activos (1*), Costos (5*), Gastos (6*)
            is_debit_nature = (
                account_type in [
                    AccountingAccount.AccountType.ASSET,
                    AccountingAccount.AccountType.EXPENSE,
                ]
                or code.startswith(('1', '5', '6'))
            )

            if is_debit_nature:
                net = debit - credit
                if net >= Decimal('0.00'):
                    debit_balance = net
                    credit_balance = Decimal('0.00')
                else:
                    debit_balance = Decimal('0.00')
                    credit_balance = abs(net)
            else:
                # Naturaleza Acreedora: Pasivos (2*), Capital/Patrimonio (3*), Ingresos (4*)
                net = credit - debit
                if net >= Decimal('0.00'):
                    credit_balance = net
                    debit_balance = Decimal('0.00')
                else:
                    credit_balance = Decimal('0.00')
                    debit_balance = abs(net)

            sum_debit_balance += debit_balance
            sum_credit_balance += credit_balance

            accounts.append({
                'id': row['account__id'],
                'code': code,
                'name': name,
                'account_type': account_type,
                'is_debit_nature': is_debit_nature,
                'total_debit': debit,
                'total_credit': credit,
                'debit_balance': debit_balance,
                'credit_balance': credit_balance,
            })

        diff = abs(sum_debits - sum_credits)
        is_balanced = (diff <= Decimal('0.01'))

        return {
            'accounts': accounts,
            'sum_debits': sum_debits,
            'sum_credits': sum_credits,
            'sum_debit_balance': sum_debit_balance,
            'sum_credit_balance': sum_credit_balance,
            'difference': diff,
            'is_balanced': is_balanced,
            'date_from': date_from,
            'date_to': date_to,
        }

    @classmethod
    def get_income_statement(cls, organization, date_from=None, date_to=None):
        """
        Genera el Estado de Resultados (P&L) en Tiempo Real.
        Clasifica ingresos operativos, costos directos y gastos operativos
        (incluyendo desglose formal de Nómina / INSS / Provisiones MITRAB).
        """
        lines_qs = JournalEntryLine.objects.filter(
            entry__organization=organization,
        )

        if date_from:
            lines_qs = lines_qs.filter(entry__date__gte=date_from)
        if date_to:
            lines_qs = lines_qs.filter(entry__date__lte=date_to)

        grouped = lines_qs.values(
            'account__id',
            'account__code',
            'account__name',
            'account__account_type',
        ).annotate(
            total_debit=Sum('debit'),
            total_credit=Sum('credit'),
        ).order_by('account__code')

        revenue_items = []
        cost_items = []
        payroll_items = []
        general_expense_items = []

        total_revenue = Decimal('0.00')
        total_operational_costs = Decimal('0.00')
        total_payroll_expenses = Decimal('0.00')
        total_general_expenses = Decimal('0.00')

        for row in grouped:
            code = row['account__code']
            name = row['account__name']
            account_type = row['account__account_type']
            debit = Decimal(str(row['total_debit'] or '0.00'))
            credit = Decimal(str(row['total_credit'] or '0.00'))

            # 1. INGRESOS (Clase 4* o AccountType.INCOME)
            if account_type == AccountingAccount.AccountType.INCOME or code.startswith('4'):
                net_revenue = credit - debit
                if net_revenue != Decimal('0.00'):
                    total_revenue += net_revenue
                    revenue_items.append({
                        'code': code,
                        'name': name,
                        'amount': net_revenue,
                    })

            # 2. COSTOS Y GASTOS (Clases 5*, 6* o AccountType.EXPENSE)
            elif account_type == AccountingAccount.AccountType.EXPENSE or code.startswith(('5', '6')):
                net_expense = debit - credit
                if net_expense == Decimal('0.00'):
                    continue

                # a. Costo de Ventas e Insumos Directos (51*)
                if code.startswith('51') or 'costo' in name.lower():
                    total_operational_costs += net_expense
                    cost_items.append({
                        'code': code,
                        'name': name,
                        'amount': net_expense,
                    })

                # b. Gastos de Nómina, Cargas Patronales y Provisiones (52*)
                elif code.startswith('52') or any(kw in name.lower() for kw in ['sueldo', 'salario', 'inss', 'inatec', 'provision', 'nómina']):
                    total_payroll_expenses += net_expense
                    payroll_items.append({
                        'code': code,
                        'name': name,
                        'amount': net_expense,
                    })

                # c. Gastos Generales y de Administración (6* u otros)
                else:
                    total_general_expenses += net_expense
                    general_expense_items.append({
                        'code': code,
                        'name': name,
                        'amount': net_expense,
                    })

        gross_profit = total_revenue - total_operational_costs
        total_operating_expenses = total_operational_costs + total_payroll_expenses + total_general_expenses
        net_income = total_revenue - total_operating_expenses

        if total_revenue > Decimal('0.00'):
            net_margin_pct = ((net_income / total_revenue) * Decimal('100')).quantize(Decimal('0.01'))
        else:
            net_margin_pct = Decimal('0.00')

        return {
            'revenue_items': revenue_items,
            'total_revenue': total_revenue,
            'cost_items': cost_items,
            'total_operational_costs': total_operational_costs,
            'gross_profit': gross_profit,
            'payroll_items': payroll_items,
            'total_payroll_expenses': total_payroll_expenses,
            'general_expense_items': general_expense_items,
            'total_general_expenses': total_general_expenses,
            'total_operating_expenses': total_operating_expenses,
            'net_income': net_income,
            'net_margin_pct': net_margin_pct,
            'date_from': date_from,
            'date_to': date_to,
        }

    @classmethod
    def get_balance_sheet(cls, organization, as_of_date=None):
        """
        Genera el Balance General (Estado de Situación Financiera).
        Agrupa Activos, Pasivos y Capital / Patrimonio, incorporando el Resultado
        del Ejercicio del P&L para validar la ecuación patrimonial:
        Activo = Pasivo + Patrimonio.
        """
        as_of = as_of_date or timezone.now().date()

        lines_qs = JournalEntryLine.objects.filter(
            entry__organization=organization,
            entry__date__lte=as_of,
        )

        grouped = lines_qs.values(
            'account__id',
            'account__code',
            'account__name',
            'account__account_type',
        ).annotate(
            total_debit=Sum('debit'),
            total_credit=Sum('credit'),
        ).order_by('account__code')

        cash_and_banks = []
        receivables = []
        tax_assets = []
        inventories = []
        other_assets = []

        accounts_payable = []
        tax_payables = []
        payroll_payables = []
        other_liabilities = []

        equity_items = []

        total_assets = Decimal('0.00')
        total_liabilities = Decimal('0.00')
        equity_accounts_total = Decimal('0.00')

        for row in grouped:
            code = row['account__code']
            name = row['account__name']
            account_type = row['account__account_type']
            debit = Decimal(str(row['total_debit'] or '0.00'))
            credit = Decimal(str(row['total_credit'] or '0.00'))

            # 1. ACTIVOS (Clase 1*)
            if account_type == AccountingAccount.AccountType.ASSET or code.startswith('1'):
                balance = debit - credit
                if balance == Decimal('0.00'):
                    continue
                total_assets += balance
                item = {'code': code, 'name': name, 'balance': balance}

                if code.startswith(('1101', '1102')):
                    cash_and_banks.append(item)
                elif code.startswith('1103'):
                    receivables.append(item)
                elif code.startswith(('1104', '1105')):
                    tax_assets.append(item)
                elif code.startswith('1106') or 'inventario' in name.lower():
                    inventories.append(item)
                else:
                    other_assets.append(item)

            # 2. PASIVOS (Clase 2*)
            elif account_type == AccountingAccount.AccountType.LIABILITY or code.startswith('2'):
                balance = credit - debit
                if balance == Decimal('0.00'):
                    continue
                total_liabilities += balance
                item = {'code': code, 'name': name, 'balance': balance}

                if code.startswith('2101'):
                    accounts_payable.append(item)
                elif code.startswith(('2102', '2103')):
                    tax_payables.append(item)
                elif code.startswith('2104'):
                    payroll_payables.append(item)
                else:
                    other_liabilities.append(item)

            # 3. PATRIMONIO / CAPITAL (Clase 3*)
            elif account_type == AccountingAccount.AccountType.EQUITY or code.startswith('3'):
                balance = credit - debit
                if balance == Decimal('0.00'):
                    continue
                equity_accounts_total += balance
                equity_items.append({'code': code, 'name': name, 'balance': balance})

        # Utilidad / Resultado Acumulado del Ejercicio procedente del Estado de Resultados
        pnl = cls.get_income_statement(organization, date_to=as_of)
        net_income = pnl['net_income']

        total_equity_and_results = equity_accounts_total + net_income
        total_liabilities_and_equity = total_liabilities + total_equity_and_results

        diff = abs(total_assets - total_liabilities_and_equity)
        is_balanced = (diff <= Decimal('0.01'))

        return {
            'as_of_date': as_of,
            # Activos
            'cash_and_banks': cash_and_banks,
            'receivables': receivables,
            'tax_assets': tax_assets,
            'inventories': inventories,
            'other_assets': other_assets,
            'total_assets': total_assets,
            # Pasivos
            'accounts_payable': accounts_payable,
            'tax_payables': tax_payables,
            'payroll_payables': payroll_payables,
            'other_liabilities': other_liabilities,
            'total_liabilities': total_liabilities,
            # Patrimonio
            'equity_items': equity_items,
            'equity_accounts_total': equity_accounts_total,
            'net_income': net_income,
            'total_equity_and_results': total_equity_and_results,
            # Verificación Ecuación Contable
            'total_liabilities_and_equity': total_liabilities_and_equity,
            'accounting_equation_diff': diff,
            'is_balanced': is_balanced,
        }
